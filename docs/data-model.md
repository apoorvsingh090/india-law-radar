# Data model (planned — enforced from Milestone 2)

Tables per build spec §5: `sources`, `documents`, `document_versions`,
`change_reports`, `citations`, `ingestion_runs`, `review_tasks`.

Rules:
- Migrations under `src/lawradar/migrations/` (SQL files, applied in order).
- Foreign keys + indexes enforced; no dual SQLite/Postgres implementations —
  one repository layer, SQLite locally, Postgres in deployment.
- Dates stay granular: signed/made, published, retrieved, commenced,
  applicable, amended — never collapsed into one `date`.
- Model output is never stored as fact without provenance + review status.

M1 creates only a `_meta(schema_version)` marker table via `lawradar init`
so the sqlite path is proven before the real schema lands.

**Milestone 2 update:** `src/lawradar/migrations/001_init.sql` creates the full schema
(sources, documents, document_versions with UNIQUE(document_id,
content_sha256), change_reports, citations, ingestion_runs, review_tasks).
`lawradar init` applies migrations; the pipeline writes sources,
documents, versions, and runs. Reports/citations/review rows arrive in
M3/M4.

**Milestone 3 update:** `change_reports` + `citations` are now written by
ingest (one draft per new version; duplicates create nothing) and by
`reports generate`. `review_tasks` still arrives with the review queue
(M4).

**Milestone 4 update:** `review_tasks` is written (auto-queue on
`unknown`/non-`ok`/amendment signals; every decision appends history),
`citations.verification_status` is set by `reports verify`,
`change_reports.published_at` is set only by `review --approve`, and
migration `002` adds `change_reports.ai_attempts` for model-attempt
history.

**Milestone 5 update:** migration `003` adds `search_index` (one row per
version: title + extracted body) mirrored into FTS5 `search_fts` by
triggers. The pipeline indexes each new version; `ensure_indexed`
backfills pre-M5 databases on first search.

**Milestone 6-10 updates:** `004` adds `feedback`; `005` adds
`sources.retired_at` so entries removed from the registry stop alerting
without deleting history. Backups are whole-file SQLite snapshots
with sidecars/manifests (`db/backup.py`), not a new table; `_migrations`
is read to prove a restored file belongs to this schema.

**Milestone 11 update:** `006` adds `notification_attempts` - one row
per outbound webhook attempt (`webhook` target name, `status` =
`delivered`/`failed`, HTTP status, capped response snippet). A partial
unique index on `(change_report_id, webhook) WHERE status='delivered'`
enforces at-most-once delivery; reports stay referenced with
`ON DELETE SET NULL` so the audit trail survives report deletion.

**Milestone 12 update:** `007` adds `evidence_bundles` - the export
audit trail (path is unique so re-exports never overwrite, `sha256` and
byte size of the artifact, `has_document` flag). `change_report_id` is
`ON DELETE SET NULL` so history survives report deletion; the bundle
ZIP itself stays verifiable offline via its embedded manifest.

**Milestone 13 update:** `008` adds three columns to `documents`:
`http_etag`, `http_last_modified` (the official server's validators
from the last `200`), and `http_validated_at` (the last time the URL
answered at all, including `304`). Validators are per document because
the polled URL is the document identity; they let the next sweep send
`If-None-Match` / `If-Modified-Since` and skip downloading unchanged
bytes. Empty strings mean "no validator cached" and produce a plain
unconditional request.

**Milestone 20 note (no schema change):** evidence bundles produced from
this release use format version 2 and include `brief.md` (the readable
Markdown brief) alongside `report.json` and `diff.txt`; the manifest
hashes it, and verification in format 2 requires it. Format 1 bundles
exported earlier remain verifiable as-is.

**Milestone 17 note (no schema change):** the database runs in WAL
mode. A live deployment therefore owns `lawradar.db` plus transient
`lawradar.db-wal` and `lawradar.db-shm` sidecars; treat all three as
one unit and never hand-copy just the `.db` file while a writer is
running. `lawradar backup create` snapshots through SQLite's online
backup API, so a verified backup is a complete, self-contained database
regardless of WAL state.
