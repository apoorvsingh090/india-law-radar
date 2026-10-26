"""Atom feed unit tests (Milestone 8): published-only, escaped, ordered."""
import xml.etree.ElementTree as ET

from lawradar.web.feeds import EPOCH_STAMP, FEED_AUTHOR, FEED_ID, atom_feed


def _report(report_id, title, published_at, change_type="text_modified",
            summary="Draft explanation"):
    return {"id": report_id, "document_title": title,
            "published_at": published_at, "change_type": change_type,
            "summary": summary}


def test_empty_feed_is_valid_atom():
    feed = atom_feed([])
    assert EPOCH_STAMP in feed
    root = ET.fromstring(feed)
    assert root.tag == "{http://www.w3.org/2005/Atom}feed"
    assert root.findtext("{http://www.w3.org/2005/Atom}id") == FEED_ID
    # Atom 1.0 requires an author on the feed when entries omit one.
    assert root.findtext(
        "{http://www.w3.org/2005/Atom}author/{http://www.w3.org/2005/Atom}name"
    ) == FEED_AUTHOR


def test_entries_in_published_order_with_links():
    feed = atom_feed([
        _report(1, "Older Act", "2026-10-20T09:00:00.000Z"),
        _report(2, "Newer Act", "2026-10-22T09:00:00.000Z"),
    ])
    root = ET.fromstring(feed)
    entries = root.findall("{http://www.w3.org/2005/Atom}entry")
    assert [e.findtext("{http://www.w3.org/2005/Atom}title")
            for e in entries] == ["Newer Act — text_modified",
                                  "Older Act — text_modified"]
    hrefs = [e.find("{http://www.w3.org/2005/Atom}link").get("href")
             for e in entries]
    assert hrefs == ["/reports/2", "/reports/1"]
    # Feed-level <updated> is the newest publication time.
    assert root.findtext("{http://www.w3.org/2005/Atom}updated") == \
        "2026-10-22T09:00:00.000Z"


def test_report_text_is_escaped():
    feed = atom_feed([
        _report(3, "<script>alert(1)</script>", "2026-10-22T09:00:00.000Z",
                summary="amp & <quotes> \" '"),
    ])
    assert "<script>alert(1)</script>" not in feed
    root = ET.fromstring(feed)  # raises if escaping broke well-formedness
    entry = root.find("{http://www.w3.org/2005/Atom}entry")
    assert entry.findtext("{http://www.w3.org/2005/Atom}title") == \
        "<script>alert(1)</script> — text_modified"
    # Raw document carries entity-escaped ampersands (ET re-unescapes).
    assert "&amp;" in feed and "&lt;script&gt;" in feed
    assert entry.findtext("{http://www.w3.org/2005/Atom}summary") == \
        "amp & <quotes> \" '"


def test_feed_is_deterministic():
    rows = [_report(4, "Act", "2026-10-21T09:00:00.000Z")]
    assert atom_feed(rows) == atom_feed(list(rows))
