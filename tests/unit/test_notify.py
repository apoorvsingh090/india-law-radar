"""Outbound webhook dispatch tests: config validation, signing, at-most-once."""
import hashlib
import hmac as hmac_mod
import json
from types import SimpleNamespace

import pytest

from lawradar.db import store
from lawradar.notify.dispatch import (
    NotifyError,
    after_approval,
    build_payload,
    dispatch_pending,
    dispatch_report,
    signature_headers,
    targets_from_config,
)


@pytest.fixture()
def db(tmp_path):
    path = tmp_path / "t.db"
    store.init_db(path)
    conn = store.connect(path)
    from lawradar.sources.registry import SourceRecord

    store.upsert_source(conn, SourceRecord(
        id="s", name="S", base_url="https://example.invalid/",
        access_method="manual_import", enabled=True))
    doc = store.get_or_create_document(
        conn, source_id="s", source_document_id="d", title="Notify Act")
    ver = store.create_version(
        conn, document_id=doc, content_sha256="x" * 64,
        raw_storage_path=None, extracted_text_path=None,
        extraction_method="html", extraction_status="ok",
        parser_warnings=[], review_status="pending")
    rep = store.create_report(
        conn, document_id=doc, old_version_id=None, new_version_id=ver,
        change_type="possible_amendment",
        affected_sections=["Section 3"], summary="S")
    conn.commit()
    yield conn, doc, ver, rep
    conn.close()


def _config(webhooks, enabled=True, timeout=5.0):
    return SimpleNamespace(notify_enabled=enabled, notify_webhooks=webhooks,
                           notify_timeout_seconds=timeout)


def _publish(conn, rep):
    from lawradar.review.queue import resolve

    resolve(conn, report_id=rep, decision="approved", reviewer="R",
            notes="checked")


def test_targets_from_config_validates(db):
    assert targets_from_config(_config([])) == []
    with pytest.raises(NotifyError, match="mapping with 'url'"):
        targets_from_config(_config(["not-a-dict"]))
    with pytest.raises(NotifyError, match="missing 'url'"):
        targets_from_config(_config([{"name": "x"}]))
    with pytest.raises(NotifyError, match="http"):
        targets_from_config(_config([{"url": "ftp://example.invalid/"}]))
    with pytest.raises(NotifyError, match="unique"):
        targets_from_config(_config([
            {"name": "same", "url": "https://a.invalid/"},
            {"name": "same", "url": "https://b.invalid/"}]))
    targets = targets_from_config(_config([
        {"url": "https://hooks.invalid/one", "secret": "s1"},
        {"name": "off", "url": "http://127.0.0.1:9/x", "enabled": "false"}]))
    assert targets[0].name == "webhook-1" and targets[0].secret == "s1"
    assert targets[1].name == "off" and targets[1].enabled is False


def test_signature_headers_verifiable(db):
    target = targets_from_config(
        _config([{"url": "https://h.invalid/", "secret": "topsecret"}]))[0]
    body = b'{"event": "report.approved"}'
    headers = signature_headers(target, body, timestamp=1_700_000_000)
    assert set(headers) == {"X-LawRadar-Token"}
    token = headers["X-LawRadar-Token"]
    ts_hex, v1 = token.replace("t=", "").split(",v1=")
    assert ts_hex == "1700000000"
    expected = hmac_mod.new(b"topsecret", b"1700000000." + body,
                            hashlib.sha256).hexdigest()
    assert v1 == expected
    assert signature_headers(
        targets_from_config(_config([{"url": "https://h.invalid/"}]))[0],
        body, timestamp=1) == {}


def test_build_payload_shape(db):
    config = _config([{"url": "https://h.invalid/"}])
    conn, _, _, rep = db
    _publish(conn, rep)
    report = dict(store.get_report(conn, rep))
    payload = build_payload(
        report, dict(store.get_document(conn, report["document_id"])))
    assert payload["event"] == "report.approved"
    assert payload["app"] == "india-law-radar"
    assert payload["report_id"] == rep
    assert payload["affected_sections"] == ["Section 3"]
    json.dumps(payload, sort_keys=True)  # always serialisable
    # Unknown report id is refused before anything is sent.
    with pytest.raises(NotifyError, match="unknown report"):
        dispatch_report(conn, config, 999)


def test_dispatch_delivers_once_and_dedups(db):
    config = _config([{"url": "https://h.invalid/", "name": "one"}])
    conn, _, _, rep = db
    _publish(conn, rep)
    seen = []

    def poster(target, body, timeout):
        seen.append((target.name, json.loads(body)))
        return 200, "{}"

    outcomes = dispatch_report(conn, config, rep, poster=poster)
    assert [o["status"] for o in outcomes] == ["delivered"]
    assert seen[0][0] == "one"
    body = seen[0][1]
    assert body["report_id"] == rep
    assert body["published_at"]
    rows = store.list_notification_attempts(conn, change_report_id=rep)
    assert len(rows) == 1 and rows[0]["status"] == "delivered"
    # At most once: a repeat dispatch skips the delivered target entirely.
    def refuse(target, body, timeout):
        pytest.fail("delivered target must not be re-POSTed")

    repeat = dispatch_report(conn, config, rep, poster=refuse)
    assert [o["status"] for o in repeat] == ["deduplicated"]
    assert len(store.list_notification_attempts(conn, rep)) == 1


def test_dispatch_records_failures_per_target(db):
    config = _config([
        {"url": "https://http500.invalid/", "name": "sink"},
        {"url": "https://dns.invalid/", "name": "dark"}])
    conn, _, _, rep = db
    _publish(conn, rep)

    def poster(target, body, timeout):
        if target.name == "sink":
            return 500, "boom"
        raise NotifyError("connection refused")

    outcomes = dispatch_report(conn, config, rep, poster=poster)
    by_name = {o["webhook"]: o for o in outcomes}
    assert by_name["sink"]["status"] == "failed"
    assert by_name["sink"]["http_status"] == 500
    assert by_name["dark"]["status"] == "failed"
    assert "connection refused" in by_name["dark"]["error"]
    rows = store.list_notification_attempts(conn, change_report_id=rep)
    # Newest attempt first, so the second target leads the listing.
    assert [(r["webhook"], r["status"]) for r in rows] == \
        [("dark", "failed"), ("sink", "failed")]
    # Retry: both targets are still undelivered, so both POST again. dark
    # now succeeds; sink keeps failing. Each target's latest state wins.
    def retry_poster(target, body, timeout):
        if target.name == "dark":
            return 200, "ok"
        return 500, "down again"

    retry = dispatch_report(conn, config, rep, poster=retry_poster)
    by_name = {o["webhook"]: o for o in retry}
    assert by_name["dark"]["status"] == "delivered"
    assert by_name["sink"]["status"] == "failed"
    latest: dict[str, tuple[str, int | None]] = {}
    for r in store.list_notification_attempts(conn, rep, limit=20):
        latest.setdefault(r["webhook"], (r["status"], r["http_status"]))
    assert latest == {"dark": ("delivered", 200), "sink": ("failed", 500)}


def test_dispatch_skips_disabled_targets_and_unpublished(db):
    conn, _, _, rep = db
    # Disabled targets are skipped without any send or DB row.
    config = _config([{"url": "https://h.invalid/", "name": "off",
                       "enabled": False}])
    _publish(conn, rep)
    outcomes = dispatch_report(conn, config, rep,
                               poster=lambda *a: pytest.fail("no send"))
    assert [o["status"] for o in outcomes] == ["disabled"]
    assert store.list_notification_attempts(conn, rep) == []
    # An unpublished draft is refused before any network call, even with
    # enabled targets, because dispatch follows approval only.
    live_config = _config([{"url": "https://h.invalid/"}])
    ver = store.create_version(
        conn, document_id=1, content_sha256="y" * 64,
        raw_storage_path=None, extracted_text_path=None,
        extraction_method="html", extraction_status="ok",
        parser_warnings=[], review_status="pending")
    draft = store.create_report(
        conn, document_id=1, old_version_id=None, new_version_id=ver,
        change_type="text_modified", summary="draft")
    conn.commit()
    with pytest.raises(NotifyError, match="not published"):
        dispatch_report(conn, live_config, draft,
                        poster=lambda *a: pytest.fail("no send"))


def test_dispatch_pending_only_needs_attention(db):
    config = _config([{"url": "https://ok.invalid/", "name": "one"}])
    conn, doc, ver, rep = db
    _publish(conn, rep)
    second = store.create_report(
        conn, document_id=doc, old_version_id=None, new_version_id=ver,
        change_type="corrigendum", summary="Second")
    conn.commit()
    assert store.get_report(conn, second)["published_at"] is None

    def ok_poster(target, body, timeout):
        return 200, "ok"

    # The unpublished draft is skipped silently; only rep is delivered.
    outcomes = dispatch_pending(conn, config, poster=ok_poster)
    assert [o["status"] for o in outcomes] == ["delivered"]
    assert store.get_report(conn, second)["published_at"] is None
    # Fully-delivered reports create nothing on a repeat sweep.
    assert dispatch_pending(conn, config, poster=ok_poster) == []
    assert len(store.list_notification_attempts(conn)) == 1


def test_after_approval_never_raises(db):
    conn, _, _, rep = db
    _publish(conn, rep)
    # Disabled setup: immediate no-op.
    assert after_approval(_config([{"url": "https://h.invalid/"}],
                                  enabled=False), conn, rep) == []
    # Malformed target config: loud failed outcome, approval untouched.
    bad = _config([{"url": "javascript:alert(1)"}])
    result = after_approval(bad, conn, rep)
    assert result[0]["status"] == "failed"
    assert result[0]["webhook"] == "config"
    # Real dispatch failure: recorded, not raised.
    result = after_approval(_config([{"url": "https://dns.invalid/"}]),
                            conn, rep)
    assert result[0]["status"] == "failed"
    assert result[0]["webhook"] == "dns.invalid" or result[0]["error"]
    assert store.list_notification_attempts(conn, rep)


def test_attempt_snippets_are_capped(db):
    config = _config([{"url": "https://h.invalid/"}])
    conn, _, _, rep = db
    _publish(conn, rep)
    dispatch_report(conn, config, rep,
                    poster=lambda t, b, to: (200, "y" * 9000))
    row = store.list_notification_attempts(conn, rep)[0]
    assert len(row["response_snippet"]) <= 2000
