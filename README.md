# India Law Radar

Source-verifiable monitoring of official Indian legal documents.
**Milestone 2 (this release):** document ingestion — source registry,
safe fetcher (allowlist + throttling), SHA-256 dedup, HTML/text-PDF
extraction with review flagging, manual import, fixture demo, provenance.

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
lawradar --help                full usage
```

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
- M2: source registry, safe fetcher, hashing/dedup, extraction (done here)
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
