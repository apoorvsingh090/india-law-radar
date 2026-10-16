# Evaluation (targets — not claims)

Pilot targets (bounded, manually curated set, per spec §14):
- ≥95% recall of known changes in the tested source set
- ≥98% citation correctness on material claims
- Zero unflagged critical status/commencement errors in published reports
- All ingestion failures visible in dashboard/CLI
- All published reports linked to official source

**Milestone 6 update:** the set and runner exist (`lawradar eval`,
7 synthetic cases, isolated temp DB). Measured 2026-10-16: 7/7 passed,
100% recall, 100% citation correctness, 0 status errors — valid only
for that set; see `tests/evaluation/pilot_eval.md`. No real-source
measurements yet (adapters disabled pending verification).

Required M1 checks (implemented): config loads, CLI health passes,
`init` is idempotent, clean-checkout `pytest` passes.
Deterministic fixture corpus (identical/small-change/metadata-only/
scanned/missing-dates/multi-dates/amendment/malformed/timeout/bad-type)
arrives in M2/M3 with the 14 required tests.
