# Real-source pilot runbook (Milestone 8-9)

This is the operator procedure for running India Law Radar against real
official sources. It exists because automation alone is not enough: the
pilot sources verified so far (see `docs/coverage.md`) need a human for
terms checks, downloads, and publication decisions. Nothing here lets a
script approve a report — humans close every loop.

## What the pilot runs on

- `lawradar watch --once` — sweeps every enabled source whose
  `poll_interval_minutes` has elapsed (fixture and verified `http_poll`
  sources). Idempotent: identical bytes never duplicate; a failed run
  never marks a source checked-OK. Exit 1 when a sweep fails, so
  schedulers can alert.
- `lawradar ingest <id> --file PATH --title "…" [--url OFFICIAL_URL]` —
  the proven path for `manual_import` sources (India Code PDFs,
  Legislative Department uploads). Watch sweeps never touch these.
- `lawradar review <id> --approve --reviewer NAME --notes "…"` — the
  only way a report becomes visible in `/feed.xml`.
- `lawradar sources health` — separates a scheduled sweep that works
  from one that silently stopped: `stale` means no success within
  `2 x poll_interval` (min 15m), `failing` means the last check errored.
  Exit 1 when a monitored source needs attention.

## Daily loop (operator)

```powershell
# 1. Sweep everything due (scheduler-friendly; logs skip reasons)
lawradar watch --once

# 1b. Confirm the sweep is actually succeeding (exit 1 = stale/failing)
lawradar sources health

# 2. Import anything a human must download (browser → file → provenance)
lawradar ingest legislative-dept --file .\downloads\act-2026.pdf `
  --title "The … Act, 2026" --url https://www.legislative.gov.in/…

# 3. Triage: drafts are unpublished until approved
lawradar review --list
lawradar reports show <id>          # compare claims against the official page
lawradar reports verify <id>        # machine citation check first
lawradar review <id> --approve --reviewer "Your Name" --notes "compared <date>"

# 4. Readers subscribe to approved reports only
lawradar serve                      # http://127.0.0.1:8080/feed.xml
```

## Scheduling the sweep

Windows Task Scheduler (daily 06:30):

```powershell
schtasks /Create /SC DAILY /ST 06:30 /TN "IndiaLawRadar watch" `
  /TR "cmd /c cd C:\path\to\india-law-radar && .venv\Scripts\lawradar.exe watch --once >> data\watch.log 2>&1 & .venv\Scripts\lawradar.exe sources health >> data\watch.log 2>&1"
```

cron (daily 06:30; both commands exit non-zero on failure → mail
arrives; `;` still runs health if the sweep itself failed):

```cron
30 6 * * * cd /opt/india-law-radar && lawradar watch --once >> data/watch.log 2>&1; lawradar sources health >> data/watch.log 2>&1
```

Long-running mode instead of a scheduler: `lawradar watch
--poll-seconds 300` sweeps, sleeps, repeats (Ctrl-C stops cleanly;
manual_import sources are always reported as skipped, never auto-run).
Check `lawradar sources health` (or `/api/sources/health`) independently
- a live loop can still be failing every source.

## Enabling a real `http_poll` source (the gate)

Do NOT flip `enabled: true` until every step in `docs/coverage.md`
("What enabled requires") is done: robots.txt recorded, terms read and
storage status set, rate limit confirmed, 3+ samples compared
field-by-field by a human, and the sign-off written into
`docs/coverage.md`. Until then keep the source `manual_import` +
disabled polling, exactly as shipped for `indiacode` and `egazette`.

## Verifying the pilot is honest

```powershell
lawradar health                     # local setup
lawradar sources health             # sweep freshness; exit 1 if stale/failing
lawradar eval                       # 7/7 pipeline regression
pytest                              # full suite
curl http://127.0.0.1:8080/api/sources/health
curl http://127.0.0.1:8080/feed.xml # only approved reports appear
```

Feed guarantees (M8): `/feed.xml` lists **only** reports with
`published_at` set — ingestion, AI output, and the watch loop can never
add entries; only a human approval does. Fixture titles keep their
`[FIXTURE]` marker in the feed, so demo data is never mistaken for
real findings.

## When a sweep fails

Follow `docs/runbook.md` (failure → action table). Never escalate
retries against a 403/bot mitigation — switch the source to
`manual_import` and record the finding in `docs/coverage.md`.
