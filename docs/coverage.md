# Source coverage (Milestone 6 pilot — verified 2026-10-16)

All live checks below were made from the build sandbox with a clear
`IndiaLawRadar/... pilot-check` User-Agent, one page per source, no
retries hammering, no verification bypasses. Re-check before enabling
anything: sites change.

## indiacode — DISABLED, base URL corrected

- `https://www.indiacode.nic.in/` now serves a migration page redirecting
  (meta-refresh + JS, 3s) to **`https://indiacode.gov.in/`**. The registry
  was updated to the new host.
- New host from sandbox: `/robots.txt` → HTTP 500; `/sitemap.xml` →
  read timeout. Unreliable here — could be sandbox egress, could be the
  new site. **Do not enable `http_poll` until an operator confirms the
  new host serves robots/terms/listings directly.**
- Supported today: `manual-sample` import of India Code PDFs the operator
  downloads in a browser (provenance recorded, hash-pinned).

## legislative-dept — DISABLED (manual path supported)

- `/robots.txt` → HTTP 200, `User-agent: * / Allow: /`. Automated
  fetching is not disallowed by robots.
- But: homepage returned HTTP 200 once, then **HTTP 403** to the same
  plain-`urllib` client minutes later (bot mitigation), and
  `/sitemap.xml` lists MeitY ministry pages, not legislation.
- Conclusion: polite listing fetches are unreliable from automation
  here. Supported paths: (1) operator saves a listing page in a browser
  and `discover_from_listing_html` (`src/lawradar/sources/legislative.py`)
  extracts same-host Act links — off-host links are dropped with a
  warning; (2) single-file `manual_import`.
- `http_poll` for this source would only probe the base URL (M2 scope)
  and is **disabled** — a 403 probe teaches nothing and wastes budget.

## egazette — DISABLED, unreachable from sandbox

- `https://egazette.gov.in/` failed TLS verification (sandbox proxy
  interception). Verification was **not** disabled and nothing was
  retried insecurely. Live robots/terms/structure checks are open.
- `src/lawradar/sources/egazette.py` holds only URL builders + a host
  validator, unit-tested with no network.

## What "enabled" requires (per source)

1. robots.txt fetched and permits the paths (record date + content hash)
2. Terms of use read: storage + redistribution status set to
   `allowed`/`restricted` (never left `unknown` for an enabled source)
3. Rate limit confirmed; `rate_limit_seconds` set at or above it
4. A human compares 3+ ingested samples field-by-field with the official
   pages (title, authority, dates, text) and signs `docs/coverage.md`
5. Only then: `enabled: true` in `config/sources.yaml` (local, git-ignored)

## Verify yourself (operator checklist)

```powershell
lawradar sources list                    # check terms + last errors
lawradar ingest manual-sample --file .\act.pdf --title "The ... Act, 2026"
lawradar reports list                    # draft exists, unpublished
lawradar reports show 1                  # compare with the official page
lawradar reports verify 1                # machine citation check
lawradar review 1 --approve --reviewer "Name" --notes "compared 2026-10-.."
lawradar eval                            # bounded-set regression, expect 7/7
```
