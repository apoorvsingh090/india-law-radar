# Pilot evaluation record (Milestone 6)

Date: 2026-10-16 · Runner: `lawradar eval` (`src/lawradar/evaluation/runner.py`)
· Commit: see `git log` · Command output is the record; this file explains it.

## Scope (read first)

Bounded fixture set: 7 synthetic `[FIXTURE]` cases in an isolated temp
DB. These numbers measure pipeline correctness on known inputs only and
**do not generalise** to official sources, real law, or any other corpus.
Do not cite them as product performance.

## Measured results (2026-10-16)

| Metric | Value | Target |
|---|---|---|
| cases passed | 7/7 | — |
| change recall (known changes in set) | 100% | ≥95% |
| citation correctness (material claims) | 100% | ≥98% |
| critical status/commencement errors | 0 | 0 |
| failed runs visible | all (0 in set) | all |

## Cases

1. `change_detected` — v1→v2 text change ⇒ `text_modified`, Sections 1+2
   attributed, citations verify.
2. `identical_no_dup` — same bytes twice ⇒ `duplicate`, 1 version.
3. `metadata_only` — same bytes, retitled ⇒ `duplicate`, 1 version.
4. `amendment_signal` — inserted amendment language ⇒ `possible_amendment`.
5. `corrigendum_signal` — correction language ⇒ `corrigendum`.
6. `unreadable_flagged` — sub-extraction-threshold text ⇒ `unknown`,
   human task queued, commencement stays unverified.
7. `dates_unknown` — multi-date prose ⇒ `new_document`, no dates inferred.

## Human verification still open (M6 acceptance)

An operator must compare 3+ real ingested samples field-by-field against
their official pages (see docs/coverage.md checklist) and sign here.
Status: **open** — no real-source samples ingested yet (all official
adapters disabled pending verification).
