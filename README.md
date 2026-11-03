# India Law Radar

[![CI](https://img.shields.io/github/actions/workflow/status/apoorvsingh090/india-law-radar/ci.yml?branch=main)](https://github.com/apoorvsingh090/india-law-radar/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](pyproject.toml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

Source-verifiable monitoring of official Indian legal documents.
**Milestone 14 (this release):** an operator snapshot - `lawradar status`
answers "is this deployment healthy and what needs a human right now?"
from local state only: source health (ok/stale/failing, disabled/manual/
retired), document and version counts, report queue and review status,
approved reports without an evidence bundle, failed webhook attempts,
the newest backup (with sidecar presence), and the last ingestion run.
`--json` and `GET /api/status` expose the same snapshot for dashboards
and schedulers; an `attention` list names each actionable item.
Builds on M13 conditional polling (cached `ETag`/`Last-Modified`,
`304` = unchanged), M12 evidence bundles, M11 webhook notifications,
M10 verifiable backups, M9 source health, the M8 radar loop
(`lawradar watch`, Atom feed of **approved** reports), and
`docs/pilot.md`. Still zero paid dependencies.

> Scope honesty: this MVP does **not** claim complete coverage of Indian law,
> is not a substitute for a qualified advocate, and every future change report
> must link to its official source. See `docs/limitations.md`.

## Quickstart (clean checkout)

Requirements: Python 3.11+, no API keys, no Docker, no paid services.

```powershell
# 1. Create + activate a venv (Windows PowerShell)
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1

# 2. Install (editable) + dev tools
pip install -e ".[dev]"

# 3. Initialise local dirs/config/db
lawradar init

# 4. Verify
lawradar health

# 5. Run tests
pytest

# 6. Start the web UI (loopback only)
lawradar serve
# open http://127.0.0.1:8080 — dashboard, changes, report detail,
# search, sources with health badges, review queue, coverage, Atom feed
# (/feed.xml, approved reports only), and per-report webhook delivery
# status. Use --token for review POSTs if binding beyond loopback
# (serve refuses otherwise).
```

Expected: `lawradar health` prints `health: OK` with three PASS lines;
`pytest` passes (unit + integration).

## CLI (Milestone 14)

```text
lawradar init [--force]        dirs + config + migrate sqlite schema
lawradar health [--json]       config + data-dir + sqlite checks (no network)
lawradar status [--json]       operator snapshot: sources, queue, exports,
                               backup, last run + an attention list
lawradar sources list          registry with check timestamps
lawradar sources health        ok/due/stale/failing per source
                               (exit 1 if a monitored source is stale or failing)
lawradar sources check <id>    registry probe for one source
lawradar ingest <source-id>    ingest fixture / manual / http-probe source
lawradar ingest --all          ingest all enabled sources
lawradar ingest manual-sample --file PATH --title "T" [--doc-id ID]
lawradar watch [--once]        sweep due sources on their poll schedule
                               (loop with --poll-seconds; exit 1 on --once failure)
lawradar documents list        stored documents + version counts
lawradar documents show <id>   document + versions + extraction status
lawradar documents search <q>  full-text search (FTS5, LIKE fallback)
lawradar reports list        show reports (filter --document ID)
lawradar reports show <id>   report + claims + citations
lawradar reports generate    backfill anything ingest missed
lawradar reports verify <id>  deterministic citation check (exit 1 on fail)
lawradar reports summarise <id> [--ai]  reword summary (validated, no model by default)
lawradar review --list        pending human-review queue
lawradar review <id> --approve|--reject|--changes --reviewer R --notes "…"
lawradar notify list [--report ID] [--status S]   webhook attempts (audit/triage)
lawradar notify send [--report ID] [--limit N]    deliver pending targets (exit 1 on failure)
lawradar bundles create <id> [--out DIR]   export an approved report as evidence zip
lawradar bundles verify PATH    fail-closed offline verification of a bundle
lawradar bundles list [--report ID]   export history (audit table)
lawradar serve [--host 127.0.0.1] [--port 8080] [--token ...]
lawradar eval                  curated pilot evaluation set (expect 7/7)
lawradar feedback list         triage user error reports
lawradar backup create [--out DIR] [--keep N]  snapshot + checksum + manifest
lawradar backup verify PATH    integrity, schema, manifest, checksum (exit 1)
lawradar backup restore PATH --force  verify, safety-snapshot, atomic replace
lawradar --help                full usage
```

Review policy is `manual`: reports are **unpublished** until a human
approves them; rejections and change-requests require notes. AI output
can never bypass schema validation — malformed JSON or invented
citations are rejected and recorded as failed attempts.

Notifications (optional, off by default): set `notify_enabled: true` and
add `notify_webhooks` targets in `config/settings.yaml` (never
committed). After `review --approve` commits, each enabled target gets
one POST with the approved report's JSON and, when a target has a
`secret`, an `X-LawRadar-Token: t=<ts>,v1=<hmac>` header the receiver can
verify. HTTP 4xx/5xx, DNS, and timeout failures are recorded as
`failed` attempts (visible on the report page and via `notify list`);
publication is never rolled back and nothing is auto-retried.

Evidence bundles (M12): for anything already approved,
`lawradar bundles create <report-id>` writes a deterministic
`data/bundles/lawradar-evidence-r<id>-<UTC>.zip` containing
`report.json` (summary, claims, citations, review history, document
provenance, version hashes), `diff.txt`, and the original document as
`document.bin` with a `sha256` sidecar. `manifest.json` lists the
SHA-256 and byte size of every member; `lawradar bundles verify PATH`
recomputes all of them offline and refuses anything else (unknown
members, missing members, hash drift, wrong sidecar), mirroring the
M10 backup semantics. Every export is recorded in the
`evidence_bundles` audit table and shown on the report page.

Conditional polling (M13): after the first successful fetch, each
`http_poll` document stores the official server's `ETag` and
`Last-Modified` values plus a last-validated timestamp. Later sweeps
send them back as `If-None-Match` / `If-Modified-Since`; a `304` means
"checked, unchanged" - the run is healthy, nothing is downloaded or
versioned, and the validator timestamp is refreshed. `lawradar
documents show <id>` prints the cached validators, and `ingest` /
`watch` summaries include an `unchanged` counter. Servers that ignore
validators simply return `200` and behave exactly as before.

Operator snapshot (M14): `lawradar status` prints one screen of local
state - monitored sources by health, document/version counts, reports
by review status, approved reports without an evidence bundle, failed
webhook attempts, the newest backup and whether its checksum sidecar is
present, and the last ingestion run - followed by an `attention` list
(a behind-schema database flags its pending migrations there).
`--json` and `GET /api/status` serve the same snapshot. It is read-only
and exits 0 (1 only when no database exists yet); use `lawradar health`
for start-up gating and `lawradar sources health` for sweep alerting.

Try without network: `lawradar ingest fixture-sample --sources-file
config/sources.example.yaml` twice — the second run reports `changed=0`
(idempotent dedup). All fixture titles carry a `[FIXTURE]` marker and
must never be presented as real legal findings.

Overrides: `--config PATH`, `--data-dir DIR`, `--log-level LEVEL`,
or env vars `LAWRADAR_CONFIG`, `LAWRADAR_DATA_DIR`, `LAWRADAR_DB_URL`,
`LAWRADAR_LOG_LEVEL`, `LAWRADAR_LOG_FILE`. See `config/settings.example.yaml`
and `.env.example`.

## Layout

```text
config/        example YAML (local settings.yaml is git-ignored)
docs/          architecture, data-model, source-policy, evaluation, limitations,
               pilot runbook (real-source operation, M8-10), backup/restore
               (M10), evidence bundles in the runbook (M12)
src/lawradar/  cli, config, logging, db/store + db/backup, sources/*,
               ingestion/* (watch, health), extraction/*, diffing/*,
               reporting/*, review/*, ai/*, notify/dispatch (webhooks),
               evidence/* (bundles), search/fts, web/* (incl. Atom feed),
               evaluation/*
migrations/    001-008 (schema, ai_attempts, FTS index, feedback, retirement,
               notifications, bundles, http validators)
tests/         unit + integration + fixtures + evaluation notes
scripts/       operator helpers (probe script; daily pilot loop is CLI-only)
data/          local-only runtime data (git-ignored except README/.gitkeep)
```

## Roadmap

- M1: skeleton, config, logging, CLI health, tests, docs (done)
- M2: source registry, safe fetcher, hashing/dedup, extraction (done)
- M3: deterministic diff, change reports with citations (done)
- M4: review queue, citation checks, optional AI summariser (done)
- M5: web UI, FTS search, JSON API (done)
- M6: pilot adapters, evaluation set, coverage + runbook (done)
- M7: beta hardening, feedback loop, deployment docs (done)
- M8: watch sweeps, Atom feed of approved reports, pilot runbook (done)
- M9: source health/staleness, dashboard + API signals, scheduler exit code (done)
- M10: verifiable SQLite backups, restore with safety snapshot (done)
- M11: outbound webhook notifications of approved reports (done)
- M12: offline-verifiable evidence bundle exports (done)
- M13: conditional HTTP polling with cached validators (done)
- M14: operator status snapshot (`lawradar status`, `/api/status`) (done here)

## Safeguards

- No invented Acts/sections/dates/URLs — unverified stays `unknown`.
- Original bytes + URL + retrieval time + SHA-256 preserved (from M2).
- Respects robots.txt, terms, rate limits; never bypasses CAPTCHA/auth.
- See `docs/source-policy.md` and `docs/limitations.md` before adding sources.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup, testing, and source rules,
and the [Code of Conduct](CODE_OF_CONDUCT.md). Use the issue templates for
bugs and feature/source requests; beginner-friendly issues carry the
[`good first issue`](https://github.com/apoorvsingh090/india-law-radar/labels/good%20first%20issue)
label. Changes are tracked in [CHANGELOG.md](CHANGELOG.md).

## Security

Report vulnerabilities privately via
[GitHub Security Advisories](https://github.com/apoorvsingh090/india-law-radar/security/advisories);
see [SECURITY.md](SECURITY.md).
