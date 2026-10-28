"""Atom feed for published change reports (Milestone 8).

Only reports a human approved (``published_at`` set) ever enter the feed
— the manual review gate cannot be bypassed by ingestion or AI output.
Output is deterministic for a given database state and every piece of
report text is XML-escaped; entry links are relative to the feed URL, so
the feed stays correct on loopback, a proxy, or any host.
"""
from __future__ import annotations

from xml.sax.saxutils import escape

FEED_TITLE = "India Law Radar — published change reports"
FEED_ID = "urn:lawradar:published-reports"
FEED_AUTHOR = "India Law Radar"
EPOCH_STAMP = "1970-01-01T00:00:00.000Z"


def _clean(value: str) -> str:
    """Drop characters XML 1.0 cannot represent (e.g. form feed)."""
    return "".join(
        ch for ch in str(value)
        if ch in "\t\n\r"
        or 0x20 <= ord(ch) <= 0xD7FF
        or 0xE000 <= ord(ch) <= 0xFFFD
        or 0x10000 <= ord(ch) <= 0x10FFFF
    )


def _attr(value: str) -> str:
    return escape(_clean(value), {'"': "&quot;", "'": "&apos;"})


def atom_feed(reports: list[dict]) -> str:
    """Render published reports as an Atom 1.0 document (UTF-8 string).

    Entries are (re-)sorted newest-first here so feed ordering never
    depends on the caller's query discipline.
    """
    ordered = sorted(
        reports,
        key=lambda r: (str(r.get("published_at") or ""), int(r.get("id") or 0)),
        reverse=True,
    )
    updated = max((str(r.get("published_at") or "") for r in ordered),
                  default=EPOCH_STAMP)
    entries = []
    for report in ordered:
        title = (f"{report.get('document_title') or 'Report'} — "
                 f"{report.get('change_type') or 'unknown'}")
        link = f"/reports/{report.get('id')}"
        summary = str(report.get("summary") or "").strip()
        entries.append(
            "<entry>"
            f"<id>urn:lawradar:report:{report.get('id')}</id>"
            f"<title>{escape(_clean(title))}</title>"
            f"<updated>{_attr(str(report.get('published_at') or EPOCH_STAMP))}</updated>"
            f"<link rel=\"alternate\" type=\"text/html\" "
            f"href=\"{_attr(link)}\"/>"
            f"<summary>{escape(_clean(summary))}</summary>"
            "</entry>"
        )
    return (
        "<?xml version=\"1.0\" encoding=\"utf-8\"?>"
        "<feed xmlns=\"http://www.w3.org/2005/Atom\">"
        f"<title>{escape(FEED_TITLE)}</title>"
        f"<id>{FEED_ID}</id>"
        f"<updated>{_attr(updated)}</updated>"
        f"<author><name>{escape(FEED_AUTHOR)}</name></author>"
        "<link rel=\"self\" type=\"application/atom+xml\" href=\"/feed.xml\"/>"
        + "".join(entries) +
        "</feed>"
    )
