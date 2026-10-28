# Security Policy

## Reporting a vulnerability

Report **privately**, never as a public issue:

1. Preferred: GitHub Security Advisories —
   **Security tab → Report a vulnerability**
   (https://github.com/apoorvsingh090/india-law-radar/security/advisories/new).
2. Otherwise contact [@apoorvsingh090](https://github.com/apoorvsingh090)
   via GitHub's private contact options.

Please do not disclose details publicly until a fix is available.

## Scope

In scope:

- The `lawradar serve` web UI: path traversal, XSS, injection, auth bypass of
  the `--token` gate on non-loopback bindings
- Rate-limit or security-header regressions introduced after Milestone 7
- Secrets committed to the repo (`.env`, API keys, cookies) — `.gitignore`
  blocks `.env`, `*_api_key*`, `cookies.txt`; report accidental commits so they
  can be purged
- Citation-integrity bugs where fabricated or unverifiable references could be
  published as verified findings (this is a correctness-security issue for a
  legal-monitoring tool)

Out of scope:

- Issues in third-party official sources (their sites, PDFs, CAPTCHAs)
- The AI summariser inventing text — by design it is schema-validated,
  human-reviewed, and cannot publish without approval

## Design notes

- Web UI refuses to bind beyond loopback without an explicit `--token`.
- Every POST requires a loopback `Host` (when bound to loopback) and
  same-origin `Origin`/`Referer`/`Sec-Fetch-Site`; this blocks CSRF and
  DNS rebinding. `/feedback` is public but rate-limited and same-origin.
- Review policy is `manual`: unverified reports are never published.
- No telemetry and no paid services; data lives in a local directory
  (`LAWRADAR_DATA_DIR`).
- Backup checksums are unkeyed: they detect corruption and partial copies,
  not an attacker who can rewrite the DB and sidecars. Protect the backup
  directory with filesystem permissions and keep off-host copies.

## Supported versions

Only the latest code on `main` (currently `0.10.0`) is supported.
