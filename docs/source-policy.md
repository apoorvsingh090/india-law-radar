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

Real-source verification status: **none yet** — `indiacode` stays
`enabled: false` + `terms: not_reviewed`. Verified in M2: the `fixture`
adapter (labelled demo data, no network) and the `manual_import` flow
(operator-supplied file + recorded provenance). M2 `http_poll` only probes
a source's own base URL under the allowlist; per-document discovery waits
for M6 terms verification.
