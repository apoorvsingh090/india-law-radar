# Evaluation (targets — not claims)

Pilot targets (bounded, manually curated set, per spec §14):
- ≥95% recall of known changes in the tested source set
- ≥98% citation correctness on material claims
- Zero unflagged critical status/commencement errors in published reports
- All ingestion failures visible in dashboard/CLI
- All published reports linked to official source

Required M1 checks (implemented): config loads, CLI health passes,
`init` is idempotent, clean-checkout `pytest` passes.
Deterministic fixture corpus (identical/small-change/metadata-only/
scanned/missing-dates/multi-dates/amendment/malformed/timeout/bad-type)
arrives in M2/M3 with the 14 required tests.
