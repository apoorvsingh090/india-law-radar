# Contributing to India Law Radar

Thanks for contributing! India Law Radar monitors **official Indian legal
documents** with source-verifiable output. Two rules outrank everything else:

1. **No invented Acts, sections, dates, or URLs.** Unverified stays `unknown`.
2. **Nothing bypasses access controls.** Respect robots.txt, terms of service,
   and rate limits (see `docs/source-policy.md`).

## Development setup

Requirements: Python 3.11+, no API keys, no Docker, no paid services.

```powershell
# from a clean checkout
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1          # Windows; use `source .venv/bin/activate` on POSIX
pip install -e ".[dev]"
lawradar init                          # local dirs + config + sqlite schema
lawradar health                        # expect: health: OK
pytest                                 # expect all green
lawradar serve                         # web UI at http://127.0.0.1:8080
```

Offline smoke test: `lawradar ingest fixture-sample` twice — the second run
must report `changed=0`. Fixture titles carry a `[FIXTURE]` marker and must
never be presented as real legal findings.

## Making changes

- **Branch naming:** `feature/<short-description>` or `fix/<short-description>`
- **Commit messages:** concise, imperative, one logical change per commit
  (e.g. `Fail-closed citation verifier + unit tests`).
- **Layout:** code lives in `src/lawradar/`, tests in `tests/` (unit +
  integration), schema changes go in `migrations/` with a numbered file —
  never edit an applied migration.
- **Linting:** CI runs `ruff check` (critical errors block; full report is
  advisory). Run `ruff check .` before pushing.
- **Tests:** every behaviour change needs tests. `lawradar eval` should stay
  7/7 on the curated pilot set.

## Pull requests

1. Fork and branch from `main`.
2. Keep PRs focused; update `docs/` (architecture, data-model, source-policy,
   limitations) when behaviour changes.
3. Fill in the PR template — the review policy checklist matters here:
   reports stay **unpublished** until a human approves them, and AI output can
   never bypass schema validation.
4. CI must be green before review.

## Adding or changing sources

Sources must be official publishers (government of India sites/departments).
Open a **Feature request** with the official URL first and read
`docs/source-policy.md` + `docs/limitations.md` — coverage honesty is part of
the product.

## Reporting bugs

Use the **Bug report** template. Never include real personal data in logs or
screenshots attached to a public issue.

## Code of Conduct

This project follows the [Contributor Covenant](CODE_OF_CONDUCT.md).
