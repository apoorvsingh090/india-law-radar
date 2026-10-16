# India Law Radar

Source-verifiable monitoring of official Indian legal documents.
**Milestone 1 (this release):** project skeleton — config, logging, CLI (`init`, `health`), tests.

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

## CLI (Milestone 1)

```text
lawradar init [--force]        create ./data, config/settings.yaml, empty sqlite db
lawradar health [--json]       config + data-dir + sqlite checks (no network)
lawradar --help                full usage
```

Overrides: `--config PATH`, `--data-dir DIR`, `--log-level LEVEL`,
or env vars `LAWRADAR_CONFIG`, `LAWRADAR_DATA_DIR`, `LAWRADAR_DB_URL`,
`LAWRADAR_LOG_LEVEL`, `LAWRADAR_LOG_FILE`. See `config/settings.example.yaml`
and `.env.example`.

## Layout

```text
config/        example YAML (local settings.yaml is git-ignored)
docs/          architecture, data-model, source-policy, evaluation, limitations
src/lawradar/  cli, config, logging + package stubs for Milestones 2-5
migrations/    SQL migrations (start in Milestone 2)
tests/         unit + integration + fixtures + evaluation notes
scripts/       operator helpers (runbook arrives with real-source pilot)
data/          local-only runtime data (git-ignored except README/.gitkeep)
```

## Roadmap

- M1 (done here): skeleton, config, logging, CLI health, tests, docs
- M2: source registry, safe fetcher, hashing/dedup, HTML/PDF extraction
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
