# Architecture (Milestone 2)

```
CLI (argparse) → config.py → logging_config.py → local data dir + sqlite
                    ├→ sources/registry.py → DB sources table (sync on every run)
                    ├→ ingestion/pipeline.py → db/store.py → versions + runs
                    │     ├→ ingestion/fetcher.py (allowlist, throttle, cap)
                    │     ├→ ingestion/hashing.py (SHA-256, normalise)
                    │     └→ extraction/text.py (HTML / text / text-PDF)
                    └→ sources/{fixture,manual}.py (no network)
```

- `sources list` syncs the YAML registry into the DB before displaying.
- Every `ingest` opens a run row, syncs the registry, ingests, then records
  success/failure — failures never mark the source successfully checked.
- Raw bytes stored at `data/raw/<sha256>` unless the source policy is
  `restricted`; extracted text always at `data/text/<sha256>.txt`.
- M3 adds: `diffing/compare.py` (raw + normalised diff, section mapping,
  `text_modified`/`possible_amendment`/`corrigendum`/`unknown` labels) →
  `reporting/generate.py` builds a schema-validated draft (spec §8) →
  persisted to `change_reports` + `citations`. Ingest auto-generates the
  draft; `reports generate` backfills. Deterministic diff always lands
  before any AI summariser (M4).
- M4 adds: `review/queue.py` (auto-queue uncertain reports, approve-gated
  `published_at`, notes-required rejections, append-only `review_tasks`
  audit trail) → `reporting/verify.py` (machine citation check, never a
  human sign-off) → `ai/` (`HeuristicSummariser` default,
  `CommandSummariser` only with `ai.enabled` + `ai.command`, output
  validated, failures stored in `ai_attempts`).
- M5 adds: `search/fts.py` (FTS5 `search_fts` mirrored from `search_index`
  via triggers, LIKE fallback, literalised MATCH input) indexed by the
  pipeline per version → `web/server.py` (stdlib `ThreadingHTTPServer`,
  loopback default, token-gated POSTs, no tracebacks to clients) →
  `web/pages.py` (escaped templates for dashboard, feed, detail,
  documents, search, sources, review, coverage) + JSON API
  (`/api/*`, `/health`).   `lawradar serve` refuses non-loopback binds
  without `--token`.
- M6 adds: `sources/legislative.py` (same-host listing parser for
  operator-saved pages) + `sources/egazette.py` (URL builders/validator,
  no live calls) → `evaluation/runner.py` (7-case bounded set, `lawradar
  eval`) → `docs/coverage.md` (per-source live findings) +
  `docs/runbook.md` (failure table, reprocessing recipes).
- M7 adds: per-IP POST rate limiting + security headers + `--token`
  gating and same-origin/Host POST checks (CSRF, DNS rebinding) in
  `web/server.py`, `feedback` table (migration `004`) with
  `/feedback` intake auto-opening review tasks and `feedback` CLI
  triage, `/privacy` + `/limitations` pages, `docs/deployment.md` +
  `docs/feedback.md`.
- M8 adds: `ingestion/watch.py` — `lawradar watch` computes due sources
  (`enabled` + `poll_interval_minutes` elapsed since the DB's
  `last_checked_at`, which registry re-syncs never clobber) and sweeps
  them through the idempotent pipeline; manual_import sources are
  skipped with a reason (humans supply `--file`). Clock/sleep/stop are
  injectable, so the loop is unit-tested without waiting. `web/feeds.py`
  renders `/feed.xml` (Atom) strictly from `store.list_published_reports`
  — only human-approved reports (`published_at`) can ever appear.
- M9 adds: `ingestion/health.py` — pure evaluation of source rows into
  `ok` / `due` / `stale` / `failing` / `manual` / `disabled` from
  recorded timestamps only. Staleness is
  `max(15, 2 x poll_interval)` minutes without a success, so one missed
  sweep is tolerated but a stopped loop is visible. `sources health`
  (exit 1 when unhealthy), the dashboard, `/sources`, and
  `/api/sources/health` share this function; no network calls and no
  new dependencies.
- M10 adds: `db/backup.py` - `backup create` uses SQLite's online backup
  API for a consistent copy, then writes a SHA-256 sidecar and JSON
  manifest (format, source, counts, migration names). `backup verify`
  opens read-only, checks the sidecar, `integrity_check`,
  `foreign_key_check`, required tables, and manifest counts before
  trusting a file. `backup restore` verifies, snapshots the current DB
  as `lawradar-pre-restore-*`, copies to a partial file, and
  `os.replace`s it into place (removing stale WAL/SHM). `serve`/`watch`
  hold a shared runtime lock and restore requires it exclusively, so a
  live process cannot be swapped out from under itself. No new
  dependency is involved.
- M11 adds: `notify/dispatch.py` - outbound webhook fan-out that runs
  only after a human approval has committed (`after_approval` at the two
  review entry points, never inside `review.queue.resolve`). Each target
  gets one POST (stdlib `urllib`, configurable timeout, `http`/`https`
  only) with deterministic JSON and optional `X-LawRadar-Token`
  HMAC-SHA256 signing. Outcomes land in `notification_attempts`
  (migration `006`); a partial unique index enforces at-most-once per
  (report, webhook). Failures are recorded, never raised past the
  review flow, and retried only through explicit `lawradar notify send`.
  The web server carries the config so web review POSTs fan out the
  same way; `/api/notifications` exposes recent attempts.
- M12 adds: `evidence/bundle.py` - offline-verifiable exports so a third
  party can audit an approved report without access to this host or
  codebase. `bundles create` refuses anything a human has not approved,
  re-hashes the stored original against its `content_sha256` before
  including it, and writes a deterministic ZIP (fixed timestamps, no
  compression) so identical inputs give identical bytes. Verification
  re-reads the manifest, recomputes every member hash, cross-checks the
  sidecar, and enforces strict membership (no unknown or missing files;
  the manifest files table must cover every member). Writes are
  temp-file + atomic rename; the export lands in the `evidence_bundles`
  audit table (migration `007`) and on the report page. Bundle digests
  are unkeyed - like backups, they prove integrity against corruption,
  not against an attacker who can rewrite the archive and its manifest
  together.
