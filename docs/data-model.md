# Data model (planned — enforced from Milestone 2)

Tables per build spec §5: `sources`, `documents`, `document_versions`,
`change_reports`, `citations`, `ingestion_runs`, `review_tasks`.

Rules:
- Migrations under `migrations/` (SQL files, applied in order).
- Foreign keys + indexes enforced; no dual SQLite/Postgres implementations —
  one repository layer, SQLite locally, Postgres in deployment.
- Dates stay granular: signed/made, published, retrieved, commenced,
  applicable, amended — never collapsed into one `date`.
- Model output is never stored as fact without provenance + review status.

M1 creates only a `_meta(schema_version)` marker table via `lawradar init`
so the sqlite path is proven before the real schema lands.

**Milestone 2 update:** `migrations/001_init.sql` creates the full schema
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
