# Scripts

Operator helpers for the real-source pilot (Milestone 6+).

- `probe_legislative.py` — one-shot connectivity probe for the
  Legislative Department host (robots.txt + base URL status; no retry
  escalation, no verification bypass).
- The day-to-day pilot procedure — sweeps, manual imports, review,
  scheduling — lives in `docs/pilot.md` and runs entirely through the
  `lawradar` CLI (`watch`, `ingest`, `review`, `serve`), so there is no
  separate script to keep in sync.
