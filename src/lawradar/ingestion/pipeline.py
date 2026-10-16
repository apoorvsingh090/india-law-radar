"""Idempotent ingestion pipeline (Milestone 2).

Stages: discover → validate URL → fetch → provenance → hash → dedup →
store → extract → compare(via version count) → classify → log.
Deterministic diff + structured reports arrive in M3/M4; this module
records versions and extraction evidence only.

Core guarantee: re-ingesting identical bytes never creates a duplicate
version; changed bytes for the same document create a new version.
A failed run never marks its source successfully checked.
"""
from __future__ import annotations

import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path

from lawradar.db import store
from lawradar.extraction.text import extract_text
from lawradar.ingestion.fetcher import FetchError, RateLimiter, fetch_url
from lawradar.ingestion.hashing import sha256_bytes
from lawradar.search import fts as search_fts
from lawradar.sources import fixture as fixture_adapter
from lawradar.sources.manual import read_manual_file
from lawradar.sources.registry import SourceRecord, allowed_hosts, load_sources


@dataclass
class IngestResult:
    document_id: int
    version_id: int | None
    version_number: int | None
    status: str  # new_document | new_version | duplicate
    content_sha256: str
    extraction_status: str
    warnings: list[str] = field(default_factory=list)
    report_id: int | None = None


def _db_path(config) -> Path:
    prefix = "sqlite:///"
    if not str(config.db_url).startswith(prefix):
        raise ValueError("Milestone 2 supports sqlite db_url only")
    return Path(str(config.db_url)[len(prefix):])


def _data_dir(config) -> Path:
    path = Path(config.data_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def ingest_bytes(
    conn,
    *,
    source_id: str,
    source_document_id: str,
    title: str,
    raw_bytes: bytes,
    content_type: str = "text/html",
    filename: str = "",
    document_type: str = "unknown",
    issuing_authority: str = "",
    jurisdiction: str = "unknown",
    official_url: str = "",
    storage_policy: str = "unknown",
    data_dir: str | Path = "data",
) -> IngestResult:
    """Ingest one document's bytes idempotently. Returns status + evidence."""
    if not raw_bytes:
        raise ValueError("refusing to ingest empty bytes")
    data_path = Path(data_dir)
    sha = sha256_bytes(raw_bytes)
    document_id = store.get_or_create_document(
        conn,
        source_id=source_id,
        source_document_id=source_document_id,
        title=title,
        document_type=document_type,
        issuing_authority=issuing_authority,
        jurisdiction=jurisdiction,
        official_url=official_url,
    )
    if store.version_exists(conn, document_id, sha):
        row = store.latest_version(conn, document_id)
        return IngestResult(
            document_id=document_id,
            version_id=int(row["id"]),
            version_number=int(row["version_number"]),
            status="duplicate",
            content_sha256=sha,
            extraction_status=row["extraction_status"],
            warnings=["identical content hash already stored; no new version"],
        )
    is_new_document = store.count_versions(conn, document_id) == 0

    warnings: list[str] = []
    raw_storage_path: str | None = None
    if storage_policy == "restricted":
        warnings.append("original bytes not stored: source storage_policy=restricted")
    else:
        raw_dir = data_path / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        raw_file = raw_dir / sha
        if not raw_file.is_file():
            raw_file.write_bytes(raw_bytes)
        raw_storage_path = str(raw_file)

    extraction = extract_text(raw_bytes, content_type, filename)
    warnings.extend(extraction.warnings)
    text_dir = data_path / "text"
    text_dir.mkdir(parents=True, exist_ok=True)
    text_file = text_dir / f"{sha}.txt"
    text_file.write_text(extraction.text, encoding="utf-8")
    review_status = "pending" if extraction.status == "ok" else "needs_review"

    version_id = store.create_version(
        conn,
        document_id=document_id,
        content_sha256=sha,
        raw_storage_path=raw_storage_path,
        extracted_text_path=str(text_file),
        extraction_method=extraction.method,
        extraction_status=extraction.status,
        parser_warnings=warnings,
        review_status=review_status,
    )
    try:
        search_fts.index_version(
            conn, doc_id=document_id, version_id=version_id, title=title,
            text_path=str(text_file))
    except Exception as exc:  # noqa: BLE001 — search must never break ingest
        warnings.append(f"search indexing failed ({exc}); flagged for review")
    row = store.latest_version(conn, document_id)
    # Draft report for the new version. A report failure must never fail
    # the ingest itself — it is recorded as a warning for review.
    report_id: int | None = None
    try:
        from lawradar.reporting.generate import generate_for_document

        generated = generate_for_document(conn, document_id)
        if generated is not None:
            report_id = generated["report_id"]
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"report generation failed ({exc}); flagged for review")
    return IngestResult(
        document_id=document_id,
        version_id=version_id,
        version_number=int(row["version_number"]),
        status="new_document" if is_new_document else "new_version",
        content_sha256=sha,
        extraction_status=extraction.status,
        warnings=warnings,
        report_id=report_id,
    )


def ingest_manual_file(
    conn,
    config,
    source: SourceRecord,
    path: str,
    *,
    title: str,
    source_document_id: str = "",
    official_url: str = "",
    document_type: str = "unknown",
    issuing_authority: str = "",
    jurisdiction: str | None = None,
) -> IngestResult:
    """Ingest a local file through the manual-import adapter."""
    manual = read_manual_file(path)
    name = Path(path).name
    doc_id = source_document_id or name
    result = ingest_bytes(
        conn,
        source_id=source.id,
        source_document_id=doc_id,
        title=title,
        raw_bytes=manual.data,
        content_type=manual.content_type,
        filename=name,
        document_type=document_type,
        issuing_authority=issuing_authority,
        jurisdiction=jurisdiction or source.jurisdiction,
        official_url=official_url or source.base_url,
        storage_policy=source.storage_policy,
        data_dir=_data_dir(config),
    )
    result.warnings = manual.warnings + result.warnings
    return result


def _fetch_http_document(
    config, source: SourceRecord, url: str, limiter: RateLimiter
) -> tuple[bytes, str, str]:
    """Fetch one official URL under the allowlist policy."""
    hosts = {(urllib.parse.urlparse(source.base_url).hostname or "").lower()}
    result = fetch_url(
        url,
        hosts,
        timeout_seconds=config.http_timeout_seconds,
        max_bytes=config.http_max_bytes,
        rate_limiter=limiter,
        min_interval_seconds=source.rate_limit_seconds,
    )
    return result.data, result.content_type, result.final_url


def ingest_source(
    conn,
    config,
    source: SourceRecord,
    *,
    limit: int = 100,
    manual_file: str | None = None,
    manual_title: str = "",
    manual_doc_id: str = "",
) -> dict:
    """Ingest one source; returns a run summary dict (never raises)."""
    run_id = store.create_run(conn, source.id)
    discovered = downloaded = changed = failed = 0
    errors: list[str] = []
    limiter = RateLimiter(source.rate_limit_seconds)
    try:
        if source.access_method == "fixture":
            for item in fixture_adapter.list_fixtures()[:limit]:
                discovered += 1
                try:
                    result = ingest_bytes(
                        conn,
                        source_id=source.id,
                        source_document_id=item.source_document_id,
                        title=item.title,
                        raw_bytes=item.read(),
                        content_type="text/html",
                        filename=item.filename,
                        document_type=item.document_type,
                        issuing_authority=item.issuing_authority,
                        jurisdiction=item.jurisdiction,
                        official_url=item.official_url,
                        storage_policy="allowed",
                        data_dir=_data_dir(config),
                    )
                    downloaded += 1
                    if result.status in ("new_document", "new_version"):
                        changed += 1
                except Exception as exc:  # noqa: BLE001
                    failed += 1
                    errors.append(f"{item.source_document_id}: {exc}")
        elif source.access_method == "manual_import":
            if not manual_file:
                raise ValueError(
                    "manual_import sources need --file PATH "
                    "(operator downloads via permitted means first)"
                )
            discovered += 1
            result = ingest_manual_file(
                conn, config, source, manual_file,
                title=manual_title or Path(manual_file).name,
                source_document_id=manual_doc_id,
                document_type="unknown",
            )
            downloaded += 1
            if result.status in ("new_document", "new_version"):
                changed += 1
        elif source.access_method == "http_poll":
            hosts = allowed_hosts([source])
            if not hosts:
                raise ValueError("http_poll source has no fetchable host")
            # M2: http_poll discovers a single URL — the base URL itself —
            # as a smoke probe. Real per-document discovery lands in M6
            # after per-source terms verification.
            discovered += 1
            try:
                data, ctype, final_url = _fetch_http_document(
                    config, source, source.base_url, limiter
                )
                result = ingest_bytes(
                    conn,
                    source_id=source.id,
                    source_document_id=final_url,
                    title=f"{source.name} — {final_url}",
                    raw_bytes=data,
                    content_type=ctype,
                    filename=final_url,
                    issuing_authority=source.name,
                    jurisdiction=source.jurisdiction,
                    official_url=final_url,
                    storage_policy=source.storage_policy,
                    data_dir=_data_dir(config),
                )
                downloaded += 1
                if result.status in ("new_document", "new_version"):
                    changed += 1
            except (FetchError, ValueError) as exc:
                failed += 1
                errors.append(str(exc))
        else:  # pragma: no cover — registry validation forbids this
            raise ValueError(f"unknown access_method: {source.access_method}")
        conn.commit()
    except Exception as exc:  # noqa: BLE001 — run-level failure
        conn.rollback()
        failed += 1
        errors.append(str(exc))
        store.create_run(conn, source.id)  # ensure run row exists even on rollback
        run_id = store.latest_runs(conn, 1)[0]["id"]
        store.finish_run(conn, run_id, status="failed", discovered=discovered,
                         downloaded=downloaded, changed=changed, failed=failed,
                         error_summary="; ".join(errors))
        conn.commit()
        store.record_source_check(conn, source.id, False, "; ".join(errors))
        conn.commit()
        return {"run_id": run_id, "status": "failed", "changed": changed,
                "failed": failed, "errors": errors}
    # A run with any failure is never recorded as a success: only a clean
    # run updates last_success_at. Partial progress keeps its errors visible
    # on both the run row and the source row.
    clean = failed == 0
    if clean:
        status = "success"
    elif downloaded:
        status = "partial"
    else:
        status = "failed"
    store.finish_run(conn, run_id, status=status, discovered=discovered,
                     downloaded=downloaded, changed=changed, failed=failed,
                     error_summary="; ".join(errors))
    store.record_source_check(conn, source.id, clean, "; ".join(errors))
    conn.commit()
    return {"run_id": run_id, "status": status, "discovered": discovered,
            "downloaded": downloaded, "changed": changed, "failed": failed,
            "errors": errors}


def sync_registry(conn, sources: list[SourceRecord]) -> int:
    """Upsert registry entries into the DB. Returns count synced."""
    for source in sources:
        store.upsert_source(conn, source)
    conn.commit()
    return len(sources)


def run_ingestion(
    config,
    sources_file: str | None = None,
    *,
    source_id: str | None = None,
    ingest_all: bool = False,
    limit: int = 100,
    manual_file: str | None = None,
    manual_title: str = "",
    manual_doc_id: str = "",
) -> dict:
    """Entry point for the CLI: sync registry, ingest selected sources."""
    db_path = _db_path(config)
    store.init_db(db_path)
    conn = store.connect(db_path)
    try:
        sources = load_sources(sources_file)
        sync_registry(conn, sources)
        by_id = {source.id: source for source in sources}
        if ingest_all:
            selected = [source for source in sources if source.enabled]
        elif source_id:
            if source_id not in by_id:
                raise ValueError(
                    f"unknown source {source_id!r}. "
                    f"Known: {sorted(by_id) or '(none — check config/sources.yaml)'}"
                )
            selected = [by_id[source_id]]
        else:
            raise ValueError("no source selected")
        summaries = []
        for source in selected:
            summaries.append(
                ingest_source(
                    conn, config, source, limit=limit,
                    manual_file=manual_file, manual_title=manual_title,
                    manual_doc_id=manual_doc_id,
                )
            )
        return {"sources": [source.id for source in selected],
                "runs": summaries}
    finally:
        conn.close()
