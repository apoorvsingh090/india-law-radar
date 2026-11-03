# Changelog

All notable changes to India Law Radar will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.19.0] - 2026-11-03

### Added

- Milestone 19 (web browsing parity): `GET /documents` lists stored
  documents (title, source, type, jurisdiction, version count, last
  update) with `source`/`type`/`jurisdiction` filters and links to each
  document page; a `Documents` nav link exposes it
- `GET /search` gains the same filter selects and passes them into the
  FTS and LIKE search paths, so web results match `documents search`
  filters exactly
- Filter dropdown options come from `SELECT DISTINCT` over the local
  database; every value is HTML-escaped and filtering is parameterised
  SQL

## [0.18.0] - 2026-11-03

### Added

- Milestone 18 (CLI filters): `documents list` and `documents search`
  accept `--source ID`, `--type TYPE`, and `--jurisdiction J`;
  `reports list` accepts `--document ID`, `--type CHANGE_TYPE`,
  `--status VERIFICATION_STATUS`, and `--since YYYY-MM-DD` (UTC
  midnight; malformed dates exit 2)
- Filtering runs in SQL (documents/reports) and inside both search
  engines (FTS and LIKE fallback), so limits and `--json` output only
  ever contain matching rows
- `store.list_documents` gained keyword filters; `store.list_reports_filtered`
  gained `document_id`, `change_type`, and `since`; `search_fts.search`
  gained metadata filters without changing ranking

## [0.17.0] - 2026-11-03

### Changed

- Milestone 17 (durable connections): every `store.connect()` now uses
  `PRAGMA journal_mode=WAL` (falling back silently on filesystems that
  refuse it), `PRAGMA busy_timeout=5000`, `PRAGMA foreign_keys=ON`, and
  `PRAGMA synchronous=NORMAL`; a momentary writer collision waits
  instead of failing with "database is locked"
- `lawradar health` reports the journal mode it observes for the
  database (`journal=wal`), so WAL is visible evidence rather than a
  hidden setting
- Backups need no change: `backup create` already copies through
  SQLite's online backup API (WAL-safe), and `backup restore` still
  removes stale `-wal`/`-shm` sidecars. The new `tests/unit/test_store.py`
  covers the pragmas, real foreign-key enforcement, and the wait-then-
  succeed behavior under a competing writer.

## [0.16.0] - 2026-11-03

### Added

- Milestone 16 (status page): `GET /status` renders the M14 operator
  snapshot server-side - attention items, source health counts, document
  and report totals, review queue, approved reports without a bundle,
  webhook failures, a schema-pending warning, the last ingestion run,
  and the newest backup (with sidecar state)
- The dashboard shows an "items need attention" badge linking to
  `/status` whenever the attention list is non-empty
- The page is read-only, requires no JavaScript, makes no network calls,
  and escapes all stored text; `/api/status` and `lawradar status
  --json` remain the machine-readable equivalents

## [0.15.0] - 2026-11-03

### Added

- Milestone 15 (shareable briefs): `lawradar reports brief <report-id>`
  renders one approved report as deterministic Markdown - title, change
  type, status, summary, affected sections, version hashes and
  retrieval times, claims with their `c1..cN` citation labels, quoted
  citation evidence with locators and official URLs, review history,
  and reproduction commands
- `--out PATH` writes the brief to a file; `--json` returns the
  rendered text plus byte size; drafts are refused (exit 2) and unknown
  report ids exit 1
- `GET /reports/<id>/brief.md` serves the same document as a
  `text/markdown` attachment (`409` while the report is unpublished,
  `404` for unknown ids); approved report pages link to it
- Briefs render only from stored rows (no network, no model) and state
  plainly that they are not legal advice

## [0.14.0] - 2026-11-03

### Added

- Milestone 14 (operator status): `lawradar status` prints a one-screen
  snapshot derived from local state only - source health counts
  (ok/stale/failing + disabled/manual/retired), documents and versions,
  reports by review status, approved reports with no evidence bundle,
  webhook enablement and failed attempts, the newest backup (plus
  sidecar presence), and the last ingestion run
- An `attention` list names each actionable item (failing/stale source,
  pending reviews, failed webhook attempts, approved reports without an
  evidence bundle, and a database whose schema is behind the shipped
  migrations)
- `lawradar status --json` and `GET /api/status` serve the same snapshot
  for scripts and dashboards; the command is read-only, exits 0, and
  exits 1 only when the database does not exist yet
- `store.applied_migrations()` exposes the applied migration names
  read-only (used by the snapshot)

## [0.13.0] - 2026-11-03

### Added

- Milestone 13 (conditional HTTP polling): `http_poll` documents now
  cache the official server's `ETag` / `Last-Modified` validators
  (migration `008` adds `documents.http_etag`,
  `documents.http_last_modified`, `documents.http_validated_at`) and
  send them as `If-None-Match` / `If-Modified-Since` on subsequent
  sweeps
- A `304 Not Modified` answer is a healthy, unchanged check: no bytes
  are downloaded, no version or change report is created, the source's
  last-success time is refreshed, and the validator timestamp is
  stamped; `lawradar ingest` and `lawradar watch` report the count as
  `unchanged` (with `--json` included in the summary)
- Successful responses store their new validators, so a genuine edit
  still flows through the normal new-version -> diff -> report path
- `lawradar documents show <id>` prints the cached validators and the
  last-validated time

### Notes

- Servers that ignore conditional headers keep working exactly as
  before (they answer `200`, which is always accepted).

## [0.12.0] - 2026-11-03

### Added

- Milestone 12 (evidence bundles): `lawradar bundles create <report-id>`
  exports one approved change report as a single deterministic ZIP
  (`data/bundles/lawradar-evidence-r<id>-<UTC>.zip`) containing
  `report.json` (summary, claims, citations, review history, document
  provenance, version hashes), `diff.txt`, and - when the store keeps
  them - the original document bytes as `document.bin` plus a
  `document.bin.sha256` sidecar
- `manifest.json` lives inside the bundle and lists the SHA-256 and
  byte size of every other member; `lawradar bundles verify PATH`
  re-verifies offline and fails closed on missing members, unexpected
  members, any hash/size drift, wrong sidecars, or an unparsable
  manifest
- Export policy: drafts (not yet published/approved) are refused
  (exit 2), unknown report ids exit 1, and a stored original whose hash
  no longer matches the version's `content_sha256` blocks the export
  instead of amplifying corrupt data
- Every export is recorded in the new `evidence_bundles` audit table
  (migration `007`) with a unique per-report path and shown on the
  report page; `/api/bundles` exposes the history as JSON
- `lawradar bundles list` (per-report filter, `--json` supported)
- `lawradar health` now includes a `notify_config` check: a disabled
  setup passes, an enabled setup with no targets warns, and invalid
  webhook target config fails (closes the M11 loose end)
- `evidence/bundle.py` (stdlib only) with unit + real-CLI integration
  tests (roundtrip, tampering matrix, refusal paths, determinism)

## [0.11.0] - 2026-11-03

### Added

- Milestone 11 (outbound notifications): after a human approval commits,
  the approved report is POSTed as deterministic JSON to every configured
  webhook target (`notify_webhooks` in settings, off by default) with
  optional HMAC-SHA256 signing (`X-LawRadar-Token: t=<ts>,v1=<hex>` over
  `<ts>.<body>`)
- Delivery is at most once per (report, webhook): a partial unique index
  (migration `006`, `notification_attempts` table) fail-closes duplicate
  sends; repeats report `deduplicated`
- Delivery problems can never block or roll back a publication: per-target
  HTTP/DNS/timeout errors are recorded as `failed` attempts (status,
  capped response snippet) and surfaced on the report page, the dashboard,
  and `/api/notifications`
- `lawradar notify list` (audit/triage with target summary) and
  `lawradar notify send` (explicit, idempotent retry path; exit 1 when
  any target still fails; a disabled setup returns exit 2)
- Config: `notify_enabled`, `notify_webhooks` (name/url/secret/enabled),
  `notify_timeout_seconds` + `LAWRADAR_NOTIFY_ENABLED`/
  `LAWRADAR_NOTIFY_TIMEOUT_SECONDS` env overrides; only `http`/`https`
  targets accepted and names must be unique
- `notify/dispatch.py` (stdlib only) with unit + real-CLI integration
  tests against an in-process HTTP receiver

## [0.10.0] - 2026-10-28

### Added

- Milestone 10 (verifiable backups): `lawradar backup create` writes a
  consistent SQLite snapshot plus a SHA-256 sidecar and JSON manifest
  (counts, migrations, source path); `--keep N` prunes older snapshots
- `lawradar backup verify PATH` fails closed: sidecar checksum, SQLite
  `integrity_check`, foreign keys, required tables, manifest counts and
  migration names must all match before a backup is trusted
- `lawradar backup restore PATH --force` verifies the snapshot first,
  writes a `lawradar-pre-restore-*` safety backup of the current DB, and
  replaces it atomically (stale `-wal`/`-shm`/`-journal` removed)
- `db/backup.py` (stdlib only) with unit + CLI round-trip tests and
  `docs/backup.md` (schedule, restore drill, offsite rules)

### Fixed

- Audit hardening: backup retention never deletes the snapshot it just
  created (clock skew), the JSON manifest is required, stale `-journal`
  files are removed, and partial/restore temp names are collision-safe
- Publication integrity: rejecting or requesting changes after approval
  clears `published_at`, the feed requires `verification_status='approved'`,
  and re-summarising a published report is refused
- Web POSTs reject cross-origin/DNS-rebinding requests; `/feedback` is
  public without the review token and no longer copies message text into
  the review-task audit trail; malformed `Content-Length` returns 400
- Watch allows a small early-cron grace window and contains per-source
  SQLite/OS errors so one transient lock cannot stop the daemon
- Health treats an invalid/missing `created_at` as stale instead of
  disabling the never-successful alarm; sources removed from the registry
  are soft-retired (`sources.retired_at`, migration `005`) so they stop
  alerting forever while their history stays intact
- `serve`/`watch` hold a runtime lock and `backup restore` requires it,
  preventing POSIX split-brain during a live restore

## [0.9.0] - 2026-10-26

### Added

- Milestone 9 (source health): `lawradar sources health` classifies each
  source as `ok` / `due` / `stale` / `failing` (plus `manual` /
  `disabled`), prints next-due times, and exits 1 when a monitored source
  is stale or failing so schedulers can alert
- `ingestion/health.py`: deterministic, network-free health evaluation
  (stale after `max(15, 2 x poll_interval)` minutes without a success;
  `last_error` always wins); injectable clock for tests
- `/api/sources/health` JSON summary + dashboard/sources status badges
  and health details

## [0.8.0] - 2026-10-23

### Added

- Milestone 8 (radar loop): `lawradar watch` sweeps enabled sources on
  their `poll_interval_minutes` schedule — `--once` for schedulers
  (exit 1 on failure), `--poll-seconds`/`--max-sweeps` for long-running
  operation; manual_import sources are always skipped with a reason
- Atom feed `/feed.xml` of **published** reports only (publication
  remains exclusively a human review approval); feed autodiscovery +
  nav link on all pages
- `store.list_published_reports`; deterministic, XML-escaped feed
  builder (`web/feeds.py`) with a feed-level author for Atom validity
- Real-source pilot runbook `docs/pilot.md` (daily loop, scheduling,
  enabling gate, feed verification)
- GitHub Actions CI: pytest on Python 3.11 + 3.12, ruff lint gate
- Community files: `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`
- Issue forms (bug report, feature request) and pull request template

### Fixed

- Doc currency for M8: `docs/limitations.md`, `docs/coverage.md`,
  `docs/source-policy.md`, SECURITY supported version
- Fetcher User-Agent now derives from the package version (no stale
  `0.2.0` string)

## [0.7.0] - 2026-10-17

### Added

- Milestone 7 (public beta): per-IP POST rate limits, security headers,
  token-gated non-loopback serving
- Error-reporting loop (`/feedback` → review queue → feedback triage)
- Privacy and limitations pages; deployment docs
- MIT license

### Fixed

- M7 audit gaps: limitations nav, feedback resolve 404-path, doc currency

## [0.6.0] - 2026-10-16

### Added

- Milestone 6: pilot adapters, curated evaluation set (7/7), coverage notes,
  operator runbook
- Legislative-department source enabled (operator-verified); direct PDF 403
  recorded as manual-only

### Fixed

- M6 audit nits: latest-report index, migrated test URLs, unknown-kind test

## [0.5.0] - 2026-10-16

### Added

- Milestone 5: stdlib web UI, full-text search (FTS5 with LIKE fallback),
  JSON API, `lawradar serve`
- Feed summaries, detail provenance, queue changes button; API 400 handling

## [0.4.0] - 2026-10-16

### Added

- Milestone 4: human review queue, deterministic citation verification
  (fail-closed), pluggable AI summariser behind schema validation

### Fixed

- Unified diff line breaks and citation assertion

## [0.3.0] - 2026-10-16

### Added

- Milestone 3: deterministic diff, change reports with citations,
  `lawradar reports` CLI
- Persisted raw + normalized diffs in `change_reports`

### Fixed

- Partial-run success marking + regression test

## [0.2.0] - 2026-10-16

### Added

- Milestone 2: source registry, safe fetcher, hashing/dedup, extraction,
  `lawradar ingest` CLI

## [0.1.0] - 2026-10-16

### Added

- Milestone 1: project skeleton, config, logging, `lawradar health`, tests
