"""Offline-verifiable evidence bundles for approved reports (Milestone 12).

A bundle is a single ZIP archive containing everything needed to audit
one approved change report without access to the operator's host:

- ``report.json`` - the full report record: summary, claims, affected
  sections, citations, review history, document provenance, and the
  version hashes involved
- ``diff.txt`` - the deterministic diff text for the change
- ``document.bin`` + ``document.bin.sha256`` - the original downloaded
  bytes of the reported version (when the store retains them)
- ``manifest.json`` - format metadata plus the sha256 and byte size of
  every other member

Creation is refused for anything a human has not approved
(``verification_status`` must be ``approved`` and ``published_at`` set),
and refused when the stored raw file hash no longer matches the
version's ``content_sha256``: exports must never amplify corrupt data.
Verification is read-only and fails closed: missing members, extra
members, hash mismatches, a wrong sidecar, or an unparsable manifest all
refuse to trust the bundle. Writes are atomic (temporary file + replace)
and every export is recorded in the ``evidence_bundles`` audit table.
Nothing here talks to the network and no new dependency is involved.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import sqlite3
import zipfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from lawradar import __version__
from lawradar.db import store

BUNDLE_FORMAT = "lawradar-evidence-bundle"
BUNDLE_VERSION = 1
BUNDLE_PREFIX = "lawradar-evidence"
MANIFEST_MEMBER = "manifest.json"
REPORT_MEMBER = "report.json"
DIFF_MEMBER = "diff.txt"
DOCUMENT_MEMBER = "document.bin"
DOCUMENT_SIDECAR = "document.bin.sha256"
_REQUIRED_MEMBERS = frozenset({MANIFEST_MEMBER, REPORT_MEMBER, DIFF_MEMBER})
_FIXED_ZIP_DATE = (2000, 1, 1, 0, 0, 0)


class BundleError(ValueError):
    """A bundle could not be created or verified - refuse, do not guess."""


class BundleRefused(BundleError):
    """Export refused by policy (nothing was written)."""


@dataclass(frozen=True)
class BundleInfo:
    path: str
    sha256: str
    bytes: int
    report_id: int
    created_at: str
    document_title: str = ""
    document_sha256: str | None = None
    has_document: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_bytes(payload: dict) -> bytes:
    text = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True)
    return (text + "\n").encode()


def _parse_json_column(raw, label: str) -> list:
    if isinstance(raw, list):
        return raw
    try:
        return json.loads(raw) if raw else []
    except (TypeError, ValueError):
        return [f"unparseable {label} value"]


def _locate_raw(version: sqlite3.Row,
                data_dir: Path | None) -> tuple[bytes, str] | None:
    """Return (raw bytes, sha256) of the version's stored original, if any."""
    stored = version["raw_storage_path"] or ""
    candidates: list[Path] = []
    if stored:
        candidates.append(Path(stored))
    if data_dir is not None:
        # The pipeline stores original bytes as data/raw/<content_sha256>.
        candidates.append(
            Path(data_dir) / "raw" / version["content_sha256"])
    for candidate in candidates:
        try:
            if candidate.is_file():
                data = candidate.read_bytes()
                digest = _sha256_bytes(data)
                if digest != version["content_sha256"]:
                    raise BundleError(
                        f"stored raw file hash mismatch for version "
                        f"{version['id']} (expected "
                        f"{version['content_sha256'][:12]}, got "
                        f"{digest[:12]}); refusing to export corrupt data")
                return data, digest
        except OSError:
            continue
    return None


def _unique_bundle_path(out_dir: Path, name_pattern: str) -> Path:
    """Reserve a fresh bundle filename so exports never overwrite."""
    for sequence in range(1000):
        suffix = "" if sequence == 0 else f"-{sequence}"
        candidate = out_dir / f"{name_pattern}{suffix}.zip"
        try:
            fd = os.open(candidate, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            continue
        os.close(fd)
        candidate.unlink()
        return candidate
    raise BundleError("cannot allocate a unique bundle filename")


def _zip_bytes(members: dict[str, bytes]) -> bytes:
    """Deterministic ZIP: stored (no compression), fixed timestamps."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as zf:
        for name in sorted(members):
            info = zipfile.ZipInfo(name, _FIXED_ZIP_DATE)
            info.compress_type = zipfile.ZIP_STORED
            info.external_attr = 0o644 << 16
            zf.writestr(info, members[name])
    return buffer.getvalue()


def create_bundle(
    conn: sqlite3.Connection,
    report_id: int,
    out_dir: str | Path | None = None,
    *,
    data_dir: Path | None = None,
    now: datetime | None = None,
) -> BundleInfo:
    """Export one approved report as an offline-verifiable evidence bundle."""
    report = store.get_report(conn, report_id)
    if report is None:
        raise BundleError(f"unknown report id {report_id}")
    if (report["published_at"] is None
            or report["verification_status"] != "approved"):
        raise BundleRefused(
            f"report {report_id} is not approved yet; drafts cannot be "
            "exported as evidence")
    document = store.get_document(conn, report["document_id"])
    versions = store.list_versions(conn, report["document_id"])
    citations = store.list_citations(conn, report["id"])
    review_history = [dict(row) for row in conn.execute(
        "SELECT id, reason, severity, status, reviewer, review_notes,"
        " created_at, resolved_at FROM review_tasks"
        " WHERE change_report_id=? ORDER BY id", (report["id"],))]

    affected = _parse_json_column(report["affected_sections"], "affected")
    claims = _parse_json_column(report["claims_json"], "claims")
    versions_view = [dict(v) for v in versions]

    has_document = False
    document_digest: str | None = None
    document_bytes = b""
    reported_version = next(
        (v for v in versions if v["id"] == report["new_version_id"]), None)
    if reported_version is not None:
        located = _locate_raw(reported_version, data_dir)
        if located is not None:
            document_bytes, document_digest = located
            has_document = True

    report_member = {
        "report": {
            "id": report["id"],
            "document_id": report["document_id"],
            "change_type": report["change_type"],
            "summary": report["summary"],
            "affected_sections": affected,
            "claims": claims,
            "verification_status": report["verification_status"],
            "reviewer_notes": report["reviewer_notes"],
            "created_at": report["created_at"],
            "published_at": report["published_at"],
        },
        "document": {
            "id": document["id"] if document is not None else None,
            "title": (document["title"]
                      if document is not None else report["document_title"]),
            "source_id": (document["source_id"]
                          if document is not None else None),
            "source_document_id": (document["source_document_id"]
                                   if document is not None else None),
            "official_url": (document["official_url"]
                             if document is not None else ""),
            "jurisdiction": (document["jurisdiction"]
                             if document is not None else "unknown"),
            "document_type": (document["document_type"]
                              if document is not None else "unknown"),
            "issuing_authority": (document["issuing_authority"]
                                  if document is not None else ""),
            "language": (document["language"]
                         if document is not None else "en"),
        },
        "citations": [
            {"claim_id": c["claim_id"],
             "locator_type": c["locator_type"],
             "locator_value": c["locator_value"],
             "quoted_text": c["quoted_text"],
             "source_url": c["source_url"],
             "verification_status": c["verification_status"]}
            for c in citations
        ],
        "review_history": review_history,
        "versions": [
            {"version_number": v["version_number"],
             "content_sha256": v["content_sha256"],
             "retrieved_at": v["retrieved_at"],
             "extraction_status": v["extraction_status"],
             "raw_disabled": not bool(v["raw_storage_path"]),
             "is_reported_version": v["id"] == report["new_version_id"]}
            for v in versions_view
        ],
    }
    members: dict[str, bytes] = {
        REPORT_MEMBER: _json_bytes(report_member),
        DIFF_MEMBER: report["diff_text"].encode(),
    }
    if has_document:
        members[DOCUMENT_MEMBER] = document_bytes
        members[DOCUMENT_SIDECAR] = (
            f"{document_digest}  {DOCUMENT_MEMBER}\n").encode()

    moment = (now or datetime.now(UTC)).astimezone(UTC)
    created_at = moment.strftime("%Y-%m-%dT%H:%M:%SZ")
    manifest = {
        "format": BUNDLE_FORMAT,
        "version": BUNDLE_VERSION,
        "tool": f"lawradar/{__version__}",
        "created_at": created_at,
        "report_id": report["id"],
        "document_title": report_member["document"]["title"],
        "document_sha256": document_digest,
        "has_document": has_document,
        "files": {
            name: {"sha256": _sha256_bytes(data), "bytes": len(data)}
            for name, data in members.items()
        },
    }
    members[MANIFEST_MEMBER] = _json_bytes(manifest)

    out_path = Path(out_dir) if out_dir is not None else Path(
        "data") / "bundles"
    out_path.mkdir(parents=True, exist_ok=True)
    name_pattern = f"{BUNDLE_PREFIX}-r{report['id']}-" + \
        moment.strftime("%Y%m%dT%H%M%SZ")
    dest = _unique_bundle_path(out_path, name_pattern)
    partial = dest.with_name(dest.name + ".partial")
    partial.unlink(missing_ok=True)
    try:
        zip_data = _zip_bytes(members)
        partial.write_bytes(zip_data)
        os.replace(partial, dest)
    except OSError as exc:
        partial.unlink(missing_ok=True)
        raise BundleError(f"bundle write failed: {exc}") from exc
    info = BundleInfo(
        path=str(dest.resolve()), sha256=_sha256_bytes(zip_data),
        bytes=len(zip_data), report_id=int(report["id"]),
        created_at=created_at,
        document_title=report_member["document"]["title"],
        document_sha256=document_digest, has_document=has_document)
    try:
        store.record_evidence_bundle(
            conn,
            change_report_id=info.report_id,
            path=info.path,
            name=dest.name,
            sha256=info.sha256,
            bytes=info.bytes,
            has_document=has_document,
        )
        conn.commit()
    except sqlite3.Error:
        dest.unlink(missing_ok=True)
        raise BundleError(
            "bundle written but the export could not be recorded in the "
            "evidence_bundles audit table; the file was removed") from None
    return info


def verify_bundle(path: str | Path) -> BundleInfo:
    """Fail closed unless manifest, members, hashes, and sidecar all agree."""
    bundle = Path(path)
    if not bundle.is_file():
        raise BundleError(f"bundle not found: {bundle}")
    try:
        with zipfile.ZipFile(bundle) as zf:
            names = zf.namelist()
            payload = {name: zf.read(name) for name in names
                       if not name.endswith("/")}
            directories = [n for n in names if n.endswith("/")]
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
        raise BundleError(f"cannot open bundle as zip: {exc}") from exc
    if directories:
        raise BundleError(f"unexpected directory entries in bundle: "
                          f"{directories[0]}")
    if len(payload) != len(names):
        raise BundleError("duplicate member entries in bundle")
    manifest = _verify_members(payload)
    return _final_info(bundle, manifest, payload)


def _verify_members(payload: dict[str, bytes]) -> dict:
    try:
        manifest = json.loads(payload[MANIFEST_MEMBER])
    except ValueError as exc:
        raise BundleError(f"unparsable manifest: {exc}") from exc
    if not isinstance(manifest, dict):
        raise BundleError("manifest must be a JSON object")
    if manifest.get("format") != BUNDLE_FORMAT:
        raise BundleError(
            f"unsupported bundle format: {manifest.get('format')!r}")
    if manifest.get("version") != BUNDLE_VERSION:
        raise BundleError(
            f"unsupported bundle version: {manifest.get('version')!r}")
    if not manifest.get("created_at"):
        raise BundleError("manifest missing created_at")
    report_id = manifest.get("report_id")
    if not isinstance(report_id, int) or report_id < 1:
        raise BundleError("manifest report_id must be a positive integer")
    present = set(payload)
    expected = set(_REQUIRED_MEMBERS)
    if manifest.get("has_document") is True:
        expected |= {DOCUMENT_MEMBER, DOCUMENT_SIDECAR}
    missing = sorted(expected - present)
    if missing:
        raise BundleError(
            f"missing bundle member(s): {', '.join(missing)}")
    extra = sorted(present - expected)
    if extra:
        raise BundleError(
            f"unexpected bundle member(s): {', '.join(extra)}")
    files = manifest.get("files")
    if not isinstance(files, dict):
        raise BundleError("manifest missing files table")
    if set(files) != present - {MANIFEST_MEMBER}:
        raise BundleError(
            "manifest files table does not cover every bundle member")
    _verify_hashes(files, payload)
    _verify_document(manifest, payload)
    _verify_report_json(manifest, payload)
    return manifest


def _verify_hashes(files: dict, payload: dict[str, bytes]) -> None:
    for name, claimed in files.items():
        if name not in payload:
            raise BundleError(
                f"manifest lists a member that is not in the bundle: {name}")
        if not isinstance(claimed, dict) or len(claimed) != 2:
            raise BundleError(
                f"malformed manifest entry for {name} (want sha256+bytes)")
        data = payload[name]
        actual_hash = _sha256_bytes(data)
        actual_size = len(data)
        claimed_hash = claimed.get("sha256")
        claimed_size = claimed.get("bytes")
        if claimed_hash != actual_hash:
            raise BundleError(
                f"manifest hash mismatch for {name} "
                f"(expected {str(claimed_hash)[:12]}, got "
                f"{actual_hash[:12]})")
        if isinstance(claimed_size, int) and claimed_size != actual_size:
            raise BundleError(
                f"manifest size mismatch for {name} "
                f"(expected {claimed_size}, got {actual_size})")


def _verify_document(manifest: dict, payload: dict[str, bytes]) -> None:
    if manifest.get("has_document") is not True:
        if manifest.get("document_sha256") is not None:
            raise BundleError(
                "manifest claims no document but records a document hash")
        return
    sidecar = payload[DOCUMENT_SIDECAR].decode("ascii", errors="replace")
    parts = sidecar.split()
    digest = _sha256_bytes(payload[DOCUMENT_MEMBER])
    if not parts or len(parts) != 2 or parts[1] != DOCUMENT_MEMBER:
        raise BundleError(
            f"malformed {DOCUMENT_SIDECAR} (expected '<sha256>  <name>')")
    if parts[0].lower() != digest:
        raise BundleError(
            f"document sidecar mismatch (sidecar {parts[0][:12]}, actual "
            f"{digest[:12]})")
    if manifest.get("document_sha256") != digest:
        raise BundleError(
            "manifest document hash does not match document.bin")


def _verify_report_json(manifest: dict, payload: dict[str, bytes]) -> None:
    try:
        report_member = json.loads(payload[REPORT_MEMBER])
    except ValueError as exc:
        raise BundleError(f"unparsable {REPORT_MEMBER}: {exc}") from exc
    if not isinstance(report_member, dict):
        raise BundleError(f"{REPORT_MEMBER} must be a JSON object")
    bundle_report = report_member.get("report")
    if not isinstance(bundle_report, dict):
        raise BundleError(f"{REPORT_MEMBER} is missing the report record")
    if bundle_report.get("id") != manifest.get("report_id"):
        raise BundleError(
            f"{REPORT_MEMBER} report id does not match the manifest")


def _final_info(bundle: Path, manifest: dict,
                payload: dict[str, bytes]) -> BundleInfo:
    return BundleInfo(
        path=str(bundle.resolve()), sha256=_sha256_file(bundle),
        bytes=bundle.stat().st_size, report_id=int(manifest["report_id"]),
        created_at=str(manifest["created_at"]),
        document_title=str(manifest.get("document_title", "")),
        document_sha256=manifest.get("document_sha256"),
        has_document=manifest.get("has_document") is True)
