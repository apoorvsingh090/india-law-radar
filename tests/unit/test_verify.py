"""Verifier tests: fail-closed on fabricated or unchecked quotes."""
from lawradar.reporting.verify import verify_citation

TEXT = "Section 1\nFile within forty-five days of the end of the quarter.\n"
URL = "https://example.invalid/sample"


def _cite(**overrides):
    base = {"locator_type": "text span", "locator_value": "Section 1",
            "quoted_text": "File within forty-five days",
            "source_url": URL}
    base.update(overrides)
    return base


def test_honest_body_quote_passes():
    assert verify_citation(_cite(), official_url=URL,
                           version_text=TEXT)["ok"]


def test_short_fabricated_quote_fails():
    out = verify_citation(_cite(quoted_text="seven days"), official_url=URL,
                          version_text=TEXT)
    assert not out["ok"] and any("not found" in r for r in out["reasons"])


def test_missing_text_is_failure_not_pass():
    out = verify_citation(_cite(), official_url=URL, version_text="")
    assert not out["ok"] and any("no extracted text" in r for r in out["reasons"])


def test_empty_quote_fails():
    out = verify_citation(_cite(quoted_text="  "), official_url=URL,
                          version_text=TEXT)
    assert not out["ok"]


def test_url_citation_checked_against_title():
    good = _cite(locator_type="URL", locator_value=URL,
                 quoted_text="Sample Act", source_url=URL)
    assert verify_citation(good, official_url=URL, version_text=TEXT,
                           title="Sample Act")["ok"]
    bad = _cite(locator_type="URL", locator_value=URL,
                quoted_text="Some Other Act", source_url=URL)
    out = verify_citation(bad, official_url=URL, version_text=TEXT,
                          title="Sample Act")
    assert not out["ok"]


def test_wrong_official_url_fails():
    out = verify_citation(_cite(source_url="https://evil.invalid/x"),
                          official_url=URL, version_text=TEXT)
    assert not out["ok"] and any("differs" in r for r in out["reasons"])


def test_truncation_marker_stripped():
    long_quote = ("Section 1 File within forty-five days of the end of the "
                  "quarter. …[truncated]")
    assert verify_citation(_cite(quoted_text=long_quote), official_url=URL,
                           version_text=TEXT)["ok"]
