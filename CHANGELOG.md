# Changelog

All notable changes to India Law Radar will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
