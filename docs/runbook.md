# Runbook: failures and reprocessing

## Where to look

- CLI output + `lawradar health` (config, data dir, sqlite + migrations)
- `lawradar sources health` — `ok`/`due`/`stale`/`failing` per source,
  next-due times, exit 1 when a monitored source needs attention
- `lawradar sources list` — per-source `last_error`, `last_check`
- `lawradar review --list` — human-actionable queue
- Dashboard `/` — ingestion failures + coverage warnings section
- Logs: stdout/stderr (structured `timestamp | level | logger | message`);
  optional file via `LAWRADAR_LOG_FILE`

## Failure → action table

| Symptom | Likely cause | Action |
|---|---|---|
| `ingest` → `failed`, `HTTP 403` | bot mitigation / terms | Do NOT retry harder. Switch source to `manual_import`; record in coverage notes |
| `ingest` → `failed`, timeouts / 5xx | source down, slow egress | Wait out `poll_interval`; re-run `lawradar ingest <id>` (idempotent, resumes) |
| `TLS / certificate` errors | proxy / expired cert | Never disable verification. Fix egress or use browser-downloaded `manual_import` |
| `response too large` | cap hit | Raise `http_max_bytes` deliberately, or manual-import the file |
| `needs_review` versions, `unknown` reports | empty/short/scanned extraction | Open official page, compare by hand, `review --approve/--reject --notes` |
| `partial` runs | some docs failed | Fix cause, re-run ingest — successes dedup, failures retry |
| `search` empty on old DB | pre-M5 versions unindexed | `documents search` auto-backfills via `ensure_indexed`; or `reports generate` |
| `verify` → `failed` citations | quote/URL drift | Inspect `reports show`; re-ingest if the source changed; reject if fabricated |
| `watch --once` exit 1 | a source failed its sweep | Check the per-source error line above it; apply the matching row of this table — never escalate retries |
| `watch` skips a source (`not due until …`) | poll interval not elapsed | Nothing to do — the schedule is working; force with `lawradar ingest <id>` if you must |
| `watch` skips a source (`manual_import`) | by design | Humans supply the file: `lawradar ingest <id> --file PATH` (see `docs/pilot.md`) |
| `/feed.xml` missing an expected report | report not approved yet | `review --list`, then `--approve` with notes — the feed only ever lists published reports |
| `sources health` → `FAILED` (`stale`) | no successful sweep within `2 x poll_interval` (min 15m) | Check the scheduler/watch log, then `lawradar ingest <id>` once. If it succeeds, health clears; if not, apply the matching error row above |
| `sources health` → `failing` | the most recent check recorded `last_error` | Fix the cause, re-run `lawradar ingest <id>` (or wait for the next sweep) — success clears the error |
| `sources health` ignores a source | `manual` or `disabled` | By design: only enabled automated sources affect the exit code. Manual files still need `lawradar ingest <id> --file PATH` |

## Reprocessing recipes

```powershell
# Retry one source (safe: identical bytes never duplicate)
lawradar ingest <source-id>
# Retry everything enabled
lawradar ingest --all
# Backfill reports missed before M3/M4 code (idempotent)
lawradar reports generate
# Re-run citation checks after a source correction
lawradar reports verify <report-id>
# Bounded regression after any pipeline change
lawradar eval            # expect 7/7; exit 1 otherwise
pytest                   # full suite
```

## Data surgery (sqlite, local DB only)

```powershell
python -c "import sys; sys.path.insert(0,'src'); import sqlite3
from lawradar.db import store
conn = store.connect('data/lawradar.db')
print('reports:', store.count_reports(conn))
print('queue:', [dict(r) for r in store.latest_runs(conn, 5)])"
```

Back up `data/lawradar.db` before hand-editing. Never edit `content_sha256`
or history rows — append corrections as review notes instead.
