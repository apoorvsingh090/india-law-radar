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
