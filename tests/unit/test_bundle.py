"""Evidence bundle tests: creation rules, manifest hashes, fail-closed verify."""
import hashlib
import io
import json
import zipfile
from datetime import UTC, datetime

import pytest

from lawradar.db import store
from lawradar.evidence.bundle import (
    BUNDLE_FORMAT,
    DIFF_MEMBER,
    DOCUMENT_MEMBER,
    DOCUMENT_SIDECAR,
    MANIFEST_MEMBER,
    REPORT_MEMBER,
    BundleError,
    BundleRefused,
    create_bundle,
    verify_bundle,
)

RAW_V2 = b"%PDF-1.4 raw second version original bytes\n"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture()
def db(tmp_path):
    path = tmp_path / "t.db"
    store.init_db(path)
    conn = store.connect(path)
    from lawradar.sources.registry import SourceRecord

    store.upsert_source(conn, SourceRecord(
        id="s", name="S", base_url="https://example.invalid/",
        access_method="manual_import", enabled=True))
    doc = store.get_or_create_document(
        conn, source_id="s", source_document_id="d", title="Bundle Act")
    sha_v2 = _sha(RAW_V2)
    raw_dir = tmp_path / "data" / "raw"
    raw_dir.mkdir(parents=True)
    (raw_dir / sha_v2).write_bytes(RAW_V2)
    sha_v1 = _sha(b"raw first version original bytes\n")
    ver1 = store.create_version(
        conn, document_id=doc, content_sha256=sha_v1,
        raw_storage_path=None, extracted_text_path=None,
        extraction_method="html", extraction_status="ok",
        parser_warnings=[], review_status="accepted")
    ver2 = store.create_version(
        conn, document_id=doc, content_sha256=sha_v2,
        raw_storage_path=str(raw_dir / sha_v2), extracted_text_path=None,
        extraction_method="pdf-text", extraction_status="ok",
        parser_warnings=["truncated warning"], review_status="pending")
    rep = store.create_report(
        conn, document_id=doc, old_version_id=ver1, new_version_id=ver2,
        change_type="text_modified", diff_text="- line 3\n+ line 4\n",
        summary="Bundle change", affected_sections=["Section 2"],
        claims=[{
            "claim_id": "c1", "claim": "Section 2 words changed",
            "claim_type": "modification", "citation_ids": ["c1"],
        }])
    conn.commit()
    yield conn, doc, ver2, rep
    conn.close()


def _approve(conn, rep):
    from lawradar.review.queue import resolve

    resolve(conn, report_id=rep, decision="approved", reviewer="R",
            notes="checked against the official page")


def _members(path):
    with zipfile.ZipFile(path) as zf:
        return set(zf.namelist())


def _manifest(path):
    with zipfile.ZipFile(path) as zf:
        return json.loads(zf.read(MANIFEST_MEMBER))


def _report_member(path):
    with zipfile.ZipFile(path) as zf:
        return json.loads(zf.read(REPORT_MEMBER))


def _rewrite_zip(path, mutate):
    """Rebuild a zip with mutated members (simulates a tampered bundle)."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(path) as zf:
        payload = {n: zf.read(n) for n in zf.namelist()}
    mutate(payload)
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as out:
        for name, data in sorted(payload.items()):
            out.writestr(name, data)
    path.write_bytes(buffer.getvalue())


def _rewrite_manifest(path, change):
    def mutate(payload):
        manifest = json.loads(payload[MANIFEST_MEMBER])
        change(manifest)
        text = json.dumps(manifest, indent=2) + "\n"
        payload[MANIFEST_MEMBER] = text.encode()

    _rewrite_zip(path, mutate)


def test_create_refuses_draft_and_unknown(db, tmp_path):
    conn, _, _, rep = db
    out = tmp_path / "bundles"
    with pytest.raises(BundleRefused, match="not approved"):
        create_bundle(conn, rep, out)
    assert not list(out.glob("*.zip"))
    assert store.list_evidence_bundles(conn, rep) == []
    with pytest.raises(BundleError, match="unknown report id"):
        create_bundle(conn, 999, out)


def test_bundle_roundtrip_with_document(db, tmp_path):
    conn, _, _, rep = db
    _approve(conn, rep)
    out = tmp_path / "bundles"
    info = create_bundle(conn, rep, out, data_dir=tmp_path / "data")
    zips = list(out.glob("*.zip"))
    assert len(zips) == 1
    assert info.path == str(zips[0].resolve())
    assert info.report_id == rep
    assert info.has_document
    assert info.document_sha256 == _sha(RAW_V2)
    assert info.created_at.endswith("Z")
    assert info.sha256 == _sha(zips[0].read_bytes())

    checked = verify_bundle(info.path)
    assert checked.report_id == rep
    assert checked.has_document
    assert checked.document_sha256 == info.document_sha256
    assert checked.sha256 == info.sha256
    assert _members(info.path) == {
        MANIFEST_MEMBER, REPORT_MEMBER, DIFF_MEMBER,
        DOCUMENT_MEMBER, DOCUMENT_SIDECAR}

    manifest = _manifest(info.path)
    assert manifest["format"] == BUNDLE_FORMAT
    assert manifest["report_id"] == rep
    assert manifest["has_document"] is True
    assert manifest["files"][DOCUMENT_MEMBER]["bytes"] == len(RAW_V2)

    report_member = _report_member(info.path)
    assert report_member["report"]["id"] == rep
    assert report_member["report"]["summary"] == "Bundle change"
    assert report_member["report"]["affected_sections"] == ["Section 2"]
    assert report_member["report"]["claims"][0]["claim_id"] == "c1"
    assert report_member["document"]["title"] == "Bundle Act"
    history = report_member["review_history"]
    assert history and history[0]["status"] == "approved"
    assert history[0]["reviewer"] == "R"
    versions = report_member["versions"]
    reported = next(v for v in versions if v["is_reported_version"])
    assert reported["content_sha256"] == _sha(RAW_V2)
    other = next(v for v in versions if not v["is_reported_version"])
    assert other["content_sha256"] == _sha(b"raw first version original bytes\n")

    rows = store.list_evidence_bundles(conn, rep)
    assert len(rows) == 1 and rows[0]["has_document"] == 1
    assert rows[0]["sha256"] == info.sha256

    # Re-exporting the same report creates a second distinct bundle.
    create_bundle(conn, rep, out)
    rows = store.list_evidence_bundles(conn, rep)
    assert len(rows) == 2
    assert rows[0]["name"] != rows[1]["name"]


def test_bundle_without_stored_raw(db, tmp_path):
    conn, doc, _, _ = db
    ver1 = next(iter(store.list_versions(conn, doc)))
    second = store.create_report(
        conn, document_id=doc, old_version_id=None,
        new_version_id=int(ver1["id"]),
        change_type="initial_report", summary="First version report")
    conn.commit()
    _approve(conn, second)
    info = create_bundle(conn, second, tmp_path / "bundles")
    assert not info.has_document and info.document_sha256 is None
    checked = verify_bundle(info.path)
    assert not checked.has_document
    assert _members(info.path) == {MANIFEST_MEMBER, REPORT_MEMBER,
                                   DIFF_MEMBER}
    manifest = _manifest(info.path)
    assert manifest["has_document"] is False
    assert set(manifest["files"]) == {REPORT_MEMBER, DIFF_MEMBER}


def test_tampered_raw_file_refuses(db, tmp_path):
    conn, _, _, rep = db
    _approve(conn, rep)
    (tmp_path / "data" / "raw" / _sha(RAW_V2)).write_bytes(b"edited bytes")
    with pytest.raises(BundleError, match="hash mismatch"):
        create_bundle(conn, rep, tmp_path / "bundles",
                      data_dir=tmp_path / "data")
    assert list((tmp_path / "bundles").glob("*.zip")) == []
    assert store.list_evidence_bundles(conn, rep) == []


def test_deterministic_zip_bytes(db, tmp_path):
    conn, _, _, rep = db
    _approve(conn, rep)
    moment = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    first = create_bundle(conn, rep, tmp_path / "a", now=moment)
    second = create_bundle(conn, rep, tmp_path / "b", now=moment)
    with zipfile.ZipFile(first.path) as a, zipfile.ZipFile(second.path) as b:
        for name in b.namelist():
            assert a.read(name) == b.read(name)


def test_verify_fails_closed_on_tampering(db, tmp_path):
    conn, _, _, rep = db
    _approve(conn, rep)
    create_bundle(conn, rep, tmp_path, data_dir=tmp_path / "data")
    original = next(iter(tmp_path.glob("*.zip")))

    def make(mutate, name):
        clone = tmp_path / name
        clone.write_bytes(original.read_bytes())
        _rewrite_zip(clone, mutate)
        return clone

    with pytest.raises(BundleError, match="manifest hash mismatch"):
        verify_bundle(make(lambda d: d.update(
            {REPORT_MEMBER: b'{"report": {"id": 1}}'}), "flip.zip"))

    with pytest.raises(BundleError, match="unexpected bundle member"):
        verify_bundle(make(lambda d: d.update({"evil.json": b"{}"}),
                           "extra.zip"))

    with pytest.raises(BundleError, match="missing bundle member"):
        verify_bundle(make(lambda d: d.pop(DIFF_MEMBER), "lacking.zip"))

    # Manifest files table drops an entry for a member still present.
    with pytest.raises(BundleError, match="does not cover every"):
        verify_bundle(make(_rewrite_into_manifest(
            lambda m: m["files"].pop(DIFF_MEMBER)), "dropentry.zip"))

    # Document swapped but manifest still claims the original hash.
    with pytest.raises(BundleError, match="manifest hash mismatch"):
        verify_bundle(make(
            lambda d: d.update({DOCUMENT_MEMBER: b"other bytes"}),
            "swap.zip"))

    # Sidecar forged consistently (manifest updated to claim the new
    # hash too) - the verifier still cross-checks sidecar vs document.
    def forge_sidecar(payload):
        data = f"{_sha(b'zzz')}  {DOCUMENT_MEMBER}\n".encode()
        payload[DOCUMENT_SIDECAR] = data
        manifest = json.loads(payload[MANIFEST_MEMBER])
        manifest["files"][DOCUMENT_SIDECAR] = {
            "sha256": _sha(data), "bytes": len(data)}
        payload[MANIFEST_MEMBER] = (json.dumps(manifest, indent=2) + "\n") \
            .encode()

    with pytest.raises(BundleError, match="sidecar mismatch"):
        verify_bundle(make(forge_sidecar, "side.zip"))

    # Manifest claims no document while document.bin is still present.
    with pytest.raises(BundleError, match="unexpected bundle member"):
        verify_bundle(make(_rewrite_into_manifest(
            lambda m: m.update({"has_document": False})), "nodoc-claim.zip"))

    # Report id drift between manifest and report member.
    with pytest.raises(BundleError, match="report id does not match"):
        verify_bundle(make(_rewrite_into_manifest(
            lambda m: m.update({"report_id": 9999})), "drift.zip"))

    # Unsupported bundle format.
    with pytest.raises(BundleError, match="unsupported bundle format"):
        verify_bundle(make(_rewrite_into_manifest(
            lambda m: m.update({"format": "other-tool"})), "format.zip"))

    # Missing created_at.
    with pytest.raises(BundleError, match="created_at"):
        verify_bundle(make(_rewrite_into_manifest(
            lambda m: m.pop("created_at")), "nocreated.zip"))

    # Non-integer report_id.
    with pytest.raises(BundleError, match="positive integer"):
        verify_bundle(make(_rewrite_into_manifest(
            lambda m: m.update({"report_id": "nope"})), "badid.zip"))

    # Unparsable manifest.
    with pytest.raises(BundleError, match="unparsable manifest"):
        verify_bundle(make(lambda d: d.update(
            {MANIFEST_MEMBER: b"not json"}), "junk.zip"))

    # Not a zip at all + missing file.
    flat = tmp_path / "flat"
    flat.write_bytes(b"plain text")
    with pytest.raises(BundleError, match="cannot open bundle"):
        verify_bundle(flat)
    with pytest.raises(BundleError, match="bundle not found"):
        verify_bundle(tmp_path / "missing.zip")
    # The pristine original still verifies.
    assert verify_bundle(original).report_id == rep


def _rewrite_into_manifest(change):
    """Adapter: rewrite manifest json in member mutation callbacks."""
    def mutate(payload):
        manifest = json.loads(payload[MANIFEST_MEMBER])
        change(manifest)
        text = json.dumps(manifest, indent=2) + "\n"
        payload[MANIFEST_MEMBER] = text.encode()

    return mutate


def test_get_evidence_bundle_unknown(db):
    conn, *_ = db
    assert store.get_evidence_bundle(conn, 3) is None
