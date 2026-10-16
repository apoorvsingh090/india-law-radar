"""Registry tests: example loads, validation is strict."""
import pytest
import yaml

from lawradar.sources.registry import allowed_hosts, load_sources


def _write_sources(tmp_path, entries):
    path = tmp_path / "sources.yaml"
    path.write_text(yaml.safe_dump({"sources": entries}), encoding="utf-8")
    return str(path)


def _entry(**overrides):
    base = {
        "id": "test-source",
        "name": "Test Source",
        "base_url": "https://example.gov.in/docs/",
        "access_method": "http_poll",
        "terms_review_status": "not_reviewed",
        "enabled": True,
    }
    base.update(overrides)
    return base


def test_example_registry_loads():
    sources = load_sources("config/sources.example.yaml")
    by_id = {s.id for s in sources}
    assert {"fixture-sample", "manual-sample", "indiacode"} <= by_id
    fixture = next(s for s in sources if s.id == "fixture-sample")
    assert fixture.access_method == "fixture"


def test_duplicate_ids_rejected(tmp_path):
    path = _write_sources(tmp_path, [_entry(), _entry()])
    with pytest.raises(ValueError, match="duplicate source id"):
        load_sources(path)


def test_bad_url_rejected(tmp_path):
    path = _write_sources(tmp_path, [_entry(base_url="ftp://example.gov.in/")])
    with pytest.raises(ValueError, match="base_url"):
        load_sources(path)


def test_unknown_method_rejected(tmp_path):
    path = _write_sources(tmp_path, [_entry(access_method="scrape_everything")])
    with pytest.raises(ValueError, match="access_method"):
        load_sources(path)


def test_allowed_hosts_only_http_poll(tmp_path):
    path = _write_sources(tmp_path, [
        _entry(id="web", base_url="https://allowed.gov.in/"),
        _entry(id="man", base_url="https://manual.gov.in/",
               access_method="manual_import"),
    ])
    sources = load_sources(path)
    assert allowed_hosts(sources) == {"allowed.gov.in"}
