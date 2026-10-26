# Limitations (public disclosure — Milestone 8)

- Coverage: only the sources shown on `/sources` that are actually ingested.
  The pilot set is small (see `docs/coverage.md`); no completeness claim is made.
- Currency: sweeps follow each source's `poll_interval_minutes`. A skipped or
  failed sweep is visible in `lawradar watch` output, the coverage page, and
  the source's last error — silence is not proof that nothing changed.
- Publication: reports stay drafts until a human approves them. `/feed.xml`
  lists approved reports only; ingestion and AI output cannot publish.
- AI: the summariser is optional (heuristic by default, external command
  opt-in) and schema-validated. Its text is labelled draft/interpretation and
  cannot bypass human review.
- Dates/status: unknown until evidenced; presence in the database ≠ in force.
  Publication, commencement, and applicability are distinct and never inferred.
- This tool is not a substitute for a qualified advocate. Seek legal review
  before adding personalised-advice features.
- To report an error: use `/feedback` or file an issue with the source URL and
  retrieval timestamp.
