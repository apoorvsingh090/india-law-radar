# India Law Radar

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

## CLI (Milestone 2)

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
lawradar documents search <q>  keyword search (LIKE; FTS arrives in M5)
lawradar reports list        show reports (filter --document ID)
lawradar reports show <id>   report + claims + citations
lawradar reports generate    backfill anything ingest missed
lawradar reports verify <id>  deterministic citation check (exit 1 on fail)
lawradar reports summarise <id> [--ai]  reword summary (validated, no model by default)
lawradar review --list        pending human-review queue
lawradar review <id> --approve|--reject|--changes --reviewer R --notes "…"
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
               extraction/* + stubs for Milestones 3-5
migrations/    001_init.sql (full MVP schema)
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
- M3: deterministic version comparison
- M4: structured reports + review queue (LLM optional, never required)
- M5: web UI + search
- M6: real-source pilot against permitted official sources
- M7: public-beta hardening

## Safeguards

- No invented Acts/sections/dates/URLs — unverified stays `unknown`.
- Original bytes + URL + retrieval time + SHA-256 preserved (from M2).
- Respects robots.txt, terms, rate limits; never bypasses CAPTCHA/auth.
- See `docs/source-policy.md` and `docs/limitations.md` before adding sources.
