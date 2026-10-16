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
