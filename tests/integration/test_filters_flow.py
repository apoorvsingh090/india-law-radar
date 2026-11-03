"""M18 acceptance: CLI list/search filters (documents + reports)."""
import json

import pytest

from lawradar.cli import main
from lawradar.db import store


@pytest.fixture()
def seeded(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for var in ("LAWRADAR_CONFIG", "LAWRADAR_DATA_DIR", "LAWRADAR_DB_URL",
                "LAWRADAR_LOG_LEVEL", "LAWRADAR_LOG_FILE"):
        monkeypatch.delenv(var, raising=False)
    from lawradar.sources.registry import SourceRecord

    data_dir = tmp_path / "data"
    path = data_dir / "lawradar.db"
    store.init_db(path)
    conn = store.connect(path)
    try:
        store.upsert_source(conn, SourceRecord(
            id="s", name="S", base_url="https://example.invalid/",
            access_method="manual_import", enabled=True))
        act = store.get_or_create_document(
            conn, source_id="s", source_document_id="act",
            title="Filing Act", document_type="Act",
            jurisdiction="central")
        rule = store.get_or_create_document(
            conn, source_id="s", source_document_id="rule",
            title="Filing Rules", document_type="Rule",
            jurisdiction="state")
        for index, doc in enumerate((act, rule), start=1):
            ver = store.create_version(
                conn, document_id=doc, content_sha256=f"{index:064d}",
                raw_storage_path=None, extracted_text_path=None,
                extraction_method="text", extraction_status="ok",
                parser_warnings=[])
            store.create_report(
                conn, document_id=doc, old_version_id=None,
                new_version_id=ver, change_type="new_document",
                summary="First captured version.", claims=[])
            if index == 2:
                conn.execute(
                    "UPDATE change_reports SET verification_status='approved' "
                    "WHERE id=(SELECT MAX(id) FROM change_reports)")
        conn.commit()
    finally:
        conn.close()
    return str(data_dir)


def _run(seeded, *args):
    return main(["--data-dir", seeded, *args])


def test_documents_list_filters(seeded, capsys):
    assert _run(seeded, "documents", "list", "--type", "Act") == 0
    out = capsys.readouterr().out
    assert "Filing Act" in out and "Filing Rules" not in out

    assert _run(seeded, "documents", "list", "--jurisdiction", "state") == 0
    out = capsys.readouterr().out
    assert "Filing Rules" in out and "Filing Act" not in out

    assert _run(seeded, "documents", "list", "--source", "ghost") == 0
    assert "No documents stored" in capsys.readouterr().out


def test_documents_search_filters(seeded, capsys):
    assert _run(seeded, "documents", "search", "Filing",
                "--type", "Rule") == 0
    out = capsys.readouterr().out
    assert "Filing Rules" in out and "Filing Act" not in out

    assert _run(seeded, "--json", "documents", "search", "Filing",
                "--type", "Rule") == 0
    payload = json.loads(capsys.readouterr().out)
    assert [row["title"] for row in payload] == ["Filing Rules"]


def test_reports_list_filters(seeded, capsys):
    assert _run(seeded, "reports", "list", "--status", "approved") == 0
    out = capsys.readouterr().out
    assert "Filing Rules" in out and "Filing Act" not in out

    assert _run(seeded, "reports", "list", "--type", "new_document") == 0
    out = capsys.readouterr().out
    assert "Filing Act" in out and "Filing Rules" in out

    assert _run(seeded, "reports", "list", "--since", "2999-01-01") == 0
    assert "No reports yet" in capsys.readouterr().out

    assert _run(seeded, "reports", "list", "--since", "not-a-date") == 2
    assert "--since must be YYYY-MM-DD" in capsys.readouterr().err
