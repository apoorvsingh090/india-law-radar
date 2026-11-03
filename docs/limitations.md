# Limitations (public disclosure — Milestone 21)

- Coverage: only the sources shown on `/sources` that are actually ingested.
  The pilot set is small (see `docs/coverage.md`); no completeness claim is made.
- Currency: sweeps follow each source's `poll_interval_minutes`. A skipped or
  failed sweep is visible in `lawradar watch` output, `lawradar sources health`
  (stale after `2 x poll_interval`, min 15m; exit 1), the dashboard/sources
  page, `/api/sources/health`, and the source's last error — silence is not
  proof that nothing changed. Health means "the sweep ran", not "coverage is
  complete".
- Publication: reports stay drafts until a human approves them. `/feed.xml`
  lists approved reports only; ingestion and AI output cannot publish.
- AI: the summariser is optional (heuristic by default, external command
  opt-in) and schema-validated. Its text is labelled draft/interpretation and
  cannot bypass human review.
- Dates/status: unknown until evidenced; presence in the database ≠ in force.
  Publication, commencement, and applicability are distinct and never inferred.
- Notifications: disabled by default. When `notify_webhooks` targets are
  configured, approved report content (summary, sections, official URL)
  leaves the operator's host as signed JSON to chosen endpoints —
  configure only receivers trusted to hold that content. Signing
  secrets sit unencrypted in the local settings YAML (git-ignored);
  webhook URLs may be operator-chosen hosts, so only list endpoints the
  operator controls. Failures mean "this attempt failed", not
  "nobody was notified"; `notify send` is the only retry path and
  delivery is attempted at most once per (report, target).
- Evidence bundles: expiry-free exports of approved report content
  including the original document bytes - once shared, the receiver
  holds a copy of that evidence; treat bundles like published material.
  Bundle checksums are unkeyed: they detect corruption and partial
  files, not a determined attacker who rewrites both the archive and
  its manifest. Verify with `lawradar bundles verify` before trusting
  any bundle you did not export yourself.
- Conditional polling: `304 Not Modified` depends on the official server
  honouring `If-None-Match` / `If-Modified-Since`, and on that server's
  own cache correctness. A wrong validator means a real change can be
  missed until the server rotates it; servers that ignore validators
  simply re-download (the old behavior). Validators are cached per
  probed URL, so a redirect change starts an unconditional fetch again.
  A `304` proves reachability and no-change per HTTP, not legal
  non-amendment.
- Operator status: `lawradar status` reports what the local database
  knows. A green snapshot means "nothing local needs attention", not
  "coverage is complete" - a source that was never ingested cannot look
  stale, and pending-review counts say nothing about review quality.
  Never ingested sources and silent failures outside the DB are still
  only visible through `lawradar sources list` / logs.
- Briefs: `lawradar reports brief` renders stored rows only; it inherits
  every upstream limitation (extraction quality, citation verification
  status, human review depth) and adds no new checks. A brief is a
  readable summary, not evidence: it is unsigned and unhashed, so it
  proves nothing about the document itself. Forward the M12 evidence
  bundle when the artifact must be verifiable, and treat any shared
  brief as published material. It is not legal advice. Since M20 the
  same brief also ships inside evidence bundles as `brief.md`, so a
  shared ZIP contains both the readable page and the hashed evidence -
  still unkeyed integrity, not an anti-tamper seal.
- The `/status` page shows what this server's local database knows - the
  same caveats as `lawradar status` apply. It exposes counts, health
  states, and filesystem paths (database, newest backup) to anyone who
  can reach the server; the default loopback bind and the
  token-for-non-loopback rule are what limit that exposure.
- Durability: WAL mode improves concurrency, not backups of unrelated
  files. While a writer is active the live database is
  `lawradar.db` + `-wal` + `-shm`; copying only the `.db` by hand can
  capture a stale state. Use `lawradar backup create` (online backup
  API, checksummed) for any copy you intend to rely on, and keep
  off-host copies as before.
- Backups: `lawradar backup create` snapshots the SQLite DB, not raw/text
  corpora, config, or secrets. Snapshots are unencrypted and only as good
  as their off-host copy; a `.db` without its checksum/manifest sidecars is
  refused by `backup verify`, intentionally. Restore requires stopping
  `serve`/`watch`. See `docs/backup.md`.
- This tool is not a substitute for a qualified advocate. Seek legal review
  before adding personalised-advice features.
- To report an error: use `/feedback` or file an issue with the source URL and
  retrieval timestamp.
