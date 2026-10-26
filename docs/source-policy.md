# Source policy (binding for all milestones)

1. Verify terms, robots.txt, rate limits, and permitted access **before**
   implementing each adapter (India Code, eGazette, Legislative Dept, …).
2. Prefer official APIs/feeds/downloads/permitted pages. Never evade
   CAPTCHA or authentication. Defend against SSRF (allowlisted domains only).
3. Every adapter declares: id, base URL, doc types, jurisdiction, method,
   poll interval, rate limit, last check/success, coverage limits,
   storage/redistribution status, health + last error.
4. Never imply completeness or currency without source evidence.
5. Preserve issuing authority vs hosting repository vs instrument distinction.
6. A failed run must not mark a source successfully checked; a missing
   document is not a repeal without evidence.

Real-source verification status:

- `fixture` (labelled demo data, no network) and the `manual_import` flow
  (operator-supplied file + recorded provenance) were verified in M2.
- `legislative-dept` is operator-verified for **manual import only**
  (2026-10-17); automation returns HTTP 403, so it stays out of sweeps.
- `indiacode` and `egazette` remain `enabled: false` +
  `terms: not_reviewed`; enabling anything requires the checks in
  `docs/coverage.md`.
- M2 `http_poll` only probes a source's own base URL under the allowlist;
  per-document discovery remains gated on terms verification.
