"""Legislative Department adapter (Milestone 6 pilot).

Live verification status (2026-10-16, from the build sandbox):
- ``/robots.txt`` fetched HTTP 200 with ``User-agent: * / Allow: /`` —
  automated access is not disallowed by robots.
- The homepage returned HTTP 403 to a plain ``urllib`` client on a second
  visit (bot mitigation), and ``/sitemap.xml`` serves MeitY ministry
  content, not legislation. Conclusion: polite automated listing fetches
  are unreliable from here; the supported path is operator-saved listing
  pages (browser download) parsed below, or ``manual_import`` of single
  documents. ``http_poll`` stays experimental and disabled by default.

Nothing here bypasses access controls: no CAPTCHA/auth handling, no
header spoofing beyond a clear identifying User-Agent, robots honoured.
"""
from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass, field
from html.parser import HTMLParser

BASE_URL = "https://www.legislative.gov.in/"
SOURCE_ID = "legislative-dept"


class _LinkHarvester(HTMLParser):
    """Collect (href, text) pairs from anchor tags, skipping nav noise."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._text = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href:
            text = " ".join("".join(self._text).split())
            if text:
                self.links.append((self._href, text))
            self._href = None

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)


_PDF_RE = re.compile(r"\.pdf(\?|$)", re.IGNORECASE)
_ACT_HINT_RE = re.compile(r"\b(act|rule|regulation|bill|ordinance|amendment)\b",
                          re.IGNORECASE)


@dataclass
class ListingEntry:
    title: str
    url: str
    kind: str  # pdf | html | unknown
    act_hint: bool = False


@dataclass
class ListingResult:
    entries: list[ListingEntry] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def discover_from_listing_html(html_text: str, base_url: str = BASE_URL,
                               same_host_only: bool = True) -> ListingResult:
    """Parse an operator-saved official listing page into candidates.

    Never fetches anything itself. Links to other hosts are dropped
    (with a warning) unless ``same_host_only`` is False.
    """
    harvester = _LinkHarvester()
    try:
        harvester.feed(html_text)
    except Exception as exc:  # noqa: BLE001 — lenient parse, report damage
        return ListingResult(warnings=[f"listing HTML partially parsed: {exc}"])
    base_host = (urllib.parse.urlparse(base_url).hostname or "").lower()
    result = ListingResult()
    for href, text in harvester.links:
        absolute = urllib.parse.urljoin(base_url, href)
        parts = urllib.parse.urlparse(absolute)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            continue
        if same_host_only and parts.hostname.lower() != base_host:
            result.warnings.append(f"skipped off-host link: {absolute[:120]}")
            continue
        lowered = absolute.lower()
        if _PDF_RE.search(lowered):
            kind = "pdf"
        elif parts.path.endswith((".html", ".htm", "/")) or "." not in parts.path.rsplit("/", 1)[-1]:
            kind = "html"
        else:
            kind = "unknown"
        result.entries.append(ListingEntry(
            title=text, url=absolute, kind=kind,
            act_hint=bool(_ACT_HINT_RE.search(text))))
    if not result.entries:
        result.warnings.append("no document links found in listing page")
    return result
