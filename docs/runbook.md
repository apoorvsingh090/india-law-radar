# Runbook: failures and reprocessing

## Where to look

- CLI output + `lawradar health` (config, data dir, sqlite + migrations)
- `lawradar sources health` — `ok`/`due`/`stale`/`failing` per source,
  next-due times, exit 1 when a monitored source needs attention
- `lawradar sources list` — per-source `last_error`, `last_check`
- `lawradar review --list` — human-actionable queue
- `lawradar backup verify <file>` - newest snapshot trust check; see
  `docs/backup.md` for the restore drill
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
| `sources health` ignores a source | `manual`, `disabled`, or `retired` | By design: only enabled automated sources affect the exit code. Manual files still need `lawradar ingest <id> --file PATH`; retired means the id was removed from the registry (history is kept, alerts stop) |
| `backup create` -> `not a lawradar database` | wrong `--db`/data dir or uninitialised DB | Run `lawradar init` / pass `--data-dir`; verify the path, do not hand-create tables |
| `backup verify` -> `checksum mismatch` | file changed after creation or partial copy | Do NOT restore. Re-copy all three files from offsite, or pick the previous verified snapshot |
| `backup verify` -> `sidecar missing` | only the `.db` was copied | Copy `.sha256` + `.json` too; without them the verifier refuses the file by design |
| `backup restore` -> `without --force` | target DB already exists | Stop `serve`/`watch`, confirm the target, then repeat with `--force` (safety snapshot is written first) |
| `backup restore` -> `database is in use` / access denied | `serve` or `watch` holds the runtime lock | Stop `lawradar serve` and `lawradar watch`, close DB browsers and one-off ingests, then retry. The lock makes restore fail closed instead of replacing a live database |
| `backup restore` -> `safety backup (unverified)` | the old DB could not be verified, so it was preserved raw | The restore succeeded; keep the `lawradar-pre-restore-unverified-*` file for evidence, inspect it, then delete when satisfied |

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

# Snapshot before risky work, and prove it is restorable
lawradar backup create --keep 14
lawradar backup verify data\backups\<newest>.db
lawradar backup restore data\backups\<newest>.db --force   # stop serve/watch first
```

## Data surgery (sqlite, local DB only)

```powershell
python -c "import sys; sys.path.insert(0,'src'); import sqlite3
from lawradar.db import store
conn = store.connect('data/lawradar.db')
print('reports:', store.count_reports(conn))
print('queue:', [dict(r) for r in store.latest_runs(conn, 5)])"
```

Run `lawradar backup create` (and verify it) before hand-editing; a raw
file copy is not a verified snapshot. Never edit `content_sha256` or
history rows - append corrections as review notes instead.
