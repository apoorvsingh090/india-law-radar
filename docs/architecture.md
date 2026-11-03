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
- M13 adds: conditional polling in `ingestion/fetcher.py`. Each
  `http_poll` document caches the response `ETag` and `Last-Modified`
  (migration `008`: `documents.http_etag`, `http_last_modified`,
  `http_validated_at`). The fetcher replays them as `If-None-Match` /
  `If-Modified-Since`; `urllib` surfaces `304` as `HTTPError`, which the
  fetcher converts into a `FetchResult(not_modified=True)` instead of a
  failure. The pipeline then skips ingest entirely, counts the check as
  `unchanged`, refreshes the validator timestamp, and still marks the
  source successfully checked - a `304` is positive evidence that the
  official page is reachable and unchanged, not a skipped sweep. New
  validators from `200` responses replace the cached ones after the
  version is stored; servers that ignore validators behave exactly as
  before.
- M14 adds: `status.py` - a read-only operator snapshot composed from
  existing tables (source health, documents, reports, review queue,
  bundles, notification attempts, ingestion runs) plus filesystem facts
  (DB size, newest backup, checksum sidecar presence). It never touches
  the network and never writes. The same dict feeds `lawradar status`,
  `--json`, and `GET /api/status`, and an `attention` list turns the
  numbers into concrete next commands. Exit codes stay with `health`
  (setup) and `sources health` (sweeps) so the snapshot adds visibility
  without changing alerting semantics.
- M15 adds: `reporting/brief.py` - a Markdown renderer for approved
  reports, composing the rows M3/M4 already store (report JSON claims,
  citations, review tasks, version hashes) into a page a human can
  forward. It refuses anything not approved, never calls the network or
  a model, and is deterministic for a fixed generated-at stamp. The CLI
  (`reports brief`, `--out`, `--json`) and the web route
  `/reports/<id>/brief.md` share the same function, so the readable
  artifact cannot drift between interfaces. The M12 bundle remains the
  verifiable artifact; the brief is explicitly labelled not legal
  advice.
- M16 adds: the `/status` page in the web server, rendering the same
  `collect_status` dict the CLI and `/api/status` use. One composition
  function, three surfaces - nothing can drift. The dashboard embeds
  only the attention count and a link, keeping the landing page cheap;
  the status page is server-rendered HTML with every stored string
  escaped and no scripts, so the M7 security headers keep working
  unchanged.
