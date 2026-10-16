"""Pilot adapter tests: listing parser + eGazette URL helpers (no network)."""
from lawradar.sources import egazette, legislative

LISTING = """
<html><body><nav><a href="/">Home</a></nav>
<h2>Acts of Parliament 2026</h2>
<ul>
<li><a href="/sites/default/files/sample-act-2026.pdf">The Sample Act, 2026</a></li>
<li><a href="https://www.legislative.gov.in/act-2026-amendment">The Amendment Act, 2026</a></li>
<li><a href="https://evil.invalid/stolen.pdf">Not an official document</a></li>
<li><a href="mailto:info@example.invalid">Contact</a></li>
<li><a href="/rules-2026">The Sample Rules, 2026</a></li>
<li><a href="/sites/default/files/data-2026.xlsx">Dataset 2026 (not a document)</a></li>
</ul></body></html>
"""


def test_listing_parser_finds_official_docs():
    result = legislative.discover_from_listing_html(LISTING)
    urls = {e.url for e in result.entries}
    assert ("https://www.legislative.gov.in/sites/default/files/"
            "sample-act-2026.pdf") in urls
    assert "https://www.legislative.gov.in/act-2026-amendment" in urls
    assert "https://www.legislative.gov.in/rules-2026" in urls
    kinds = {e.url: e.kind for e in result.entries}
    assert kinds["https://www.legislative.gov.in/sites/default/files/"
                 "sample-act-2026.pdf"] == "pdf"
    assert kinds["https://www.legislative.gov.in/rules-2026"] == "html"
    assert kinds["https://www.legislative.gov.in/sites/default/files/"
                 "data-2026.xlsx"] == "unknown"
    assert any(e.act_hint for e in result.entries)


def test_listing_parser_drops_off_host_and_non_http():
    result = legislative.discover_from_listing_html(LISTING)
    assert all("evil.invalid" not in e.url for e in result.entries)
    assert all("mailto" not in e.url for e in result.entries)
    assert any("off-host" in w for w in result.warnings)


def test_listing_parser_empty_page_flagged():
    result = legislative.discover_from_listing_html("<html><body></body></html>")
    assert result.entries == []
    assert result.warnings


def test_egazette_url_helpers():
    assert egazette.is_gazette_url("https://egazette.gov.in/some/doc.pdf")
    assert not egazette.is_gazette_url("https://evil.invalid/x")
    assert not egazette.is_gazette_url("not a url")
    url = egazette.search_url(date_iso="2026-01-01", ministry="law")
    assert url.startswith("https://egazette.gov.in/")
    assert "2026-01-01" in url and "ministry=law" in url


def test_eval_runner_all_green():
    from lawradar.evaluation.runner import run

    result = run()
    assert result.metrics["cases"] == 7
    assert result.metrics["cases_passed"] == 7, result.cases
    assert result.metrics["change_recall"] == 1.0
    assert result.metrics["citation_correctness"] == 1.0
    assert result.metrics["status_errors"] == 0


def test_eval_cli_command(tmp_path, monkeypatch, capsys):
    from lawradar.cli import main

    monkeypatch.chdir(tmp_path)
    assert main(["eval"]) == 0
    assert "7/7" in capsys.readouterr().out
