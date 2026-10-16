"""eGazette adapter (Milestone 6 pilot) — NOT live-verified.

Status (2026-10-16, from the build sandbox): ``https://egazette.gov.in/``
could not be reached — TLS certificate verification failed (sandbox
proxy interception). Verification was NOT disabled to work around it,
and no request was retried insecurely. Live robots/terms/structure
checks, and any per-document discovery, remain for an operator with
direct access (see docs/coverage.md checklist).

This module therefore only defines the discovery URL patterns and the
validation helpers, unit-tested without network. The registry entry
stays ``enabled: false`` + ``terms_review_status: not_reviewed``.
"""
from __future__ import annotations

import urllib.parse

BASE_URL = "https://egazette.gov.in/"
SOURCE_ID = "egazette"


def search_url(date_iso: str = "", ministry: str = "") -> str:
    """Build (not fetch) the eGazette search URL for a date/ministry."""
    params = {}
    if date_iso:
        params["date"] = date_iso
    if ministry:
        params["ministry"] = ministry
    query = urllib.parse.urlencode(params)
    return urllib.parse.urljoin(BASE_URL, "search" + (f"?{query}" if query else ""))


def is_gazette_url(url: str) -> bool:
    """True when a URL belongs to the official eGazette host."""
    try:
        parts = urllib.parse.urlparse(url)
    except ValueError:
        return False
    return (parts.scheme in ("http", "https")
            and (parts.hostname or "").lower() == "egazette.gov.in")
