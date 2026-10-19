# India Law Radar

[![CI](https://img.shields.io/github/actions/workflow/status/apoorvsingh090/india-law-radar/ci.yml?branch=main)](https://github.com/apoorvsingh090/india-law-radar/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](pyproject.toml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

Source-verifiable monitoring of official Indian legal documents.
**Milestone 7 (this release — public beta):** hardening for readers —
per-IP POST rate limits, security headers, token-gated non-loopback
serving, error-reporting loop (`/feedback` → review queue → `feedback`
triage), privacy/limitations pages, and deployment docs. Still zero paid
dependencies.

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
# search, sources, review queue, coverage. Use --token for review
# POSTs if binding beyond loopback (serve refuses otherwise).
```

Expected: `lawradar health` prints `health: OK` with three PASS lines;
`pytest` passes (unit + integration).

## CLI (Milestone 7)

```text
lawradar init [--force]        dirs + config + migrate sqlite schema
lawradar health [--json]       config + data-dir + sqlite checks (no network)
lawradar sources list          registry with check timestamps
lawradar sources check <id>    registry probe for one source
lawradar ingest <source-id>    ingest fixture / manual / http-probe source
lawradar ingest --all          ingest all enabled sources
lawradar ingest manual-sample --file PATH --title "T" [--doc-id ID]
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
lawradar serve [--host 127.0.0.1] [--port 8080] [--token ...]
lawradar eval                  curated pilot evaluation set (expect 7/7)
lawradar feedback list         triage user error reports
lawradar --help                full usage
```

Review policy is `manual`: reports are **unpublished** until a human
approves them; rejections and change-requests require notes. AI output
can never bypass schema validation — malformed JSON or invented
citations are rejected and recorded as failed attempts.

Try without network: `lawradar ingest fixture-sample` twice — the second
run reports `changed=0` (idempotent dedup). All fixture titles carry a
`[FIXTURE]` marker and must never be presented as real legal findings.

Overrides: `--config PATH`, `--data-dir DIR`, `--log-level LEVEL`,
or env vars `LAWRADAR_CONFIG`, `LAWRADAR_DATA_DIR`, `LAWRADAR_DB_URL`,
`LAWRADAR_LOG_LEVEL`, `LAWRADAR_LOG_FILE`. See `config/settings.example.yaml`
and `.env.example`.

## Layout

```text
config/        example YAML (local settings.yaml is git-ignored)
docs/          architecture, data-model, source-policy, evaluation, limitations
src/lawradar/  cli, config, logging, db/store, sources/*, ingestion/*,
               extraction/*, diffing/*, reporting/*, review/*, ai/*,
               search/fts, web/*, evaluation/*
migrations/    001-004 (schema, ai_attempts, FTS index, feedback)
tests/         unit + integration + fixtures + evaluation notes
scripts/       operator helpers (runbook arrives with real-source pilot)
data/          local-only runtime data (git-ignored except README/.gitkeep)
```

## Roadmap

- M1: skeleton, config, logging, CLI health, tests, docs (done)
- M2: source registry, safe fetcher, hashing/dedup, extraction (done)
- M3: deterministic diff, change reports with citations (done)
- M4: review queue, citation checks, optional AI summariser (done)
- M5: web UI, FTS search, JSON API (done)
- M6: pilot adapters, evaluation set, coverage + runbook (done)
- M7: beta hardening, feedback loop, deployment docs (done here)

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
