"""Public-beta unit tests: rate limiter, feedback store, headers."""
import pytest

from lawradar.db import store
from lawradar.web.server import SECURITY_HEADERS, RateLimiter


def test_rate_limiter_blocks_over_limit():
    limiter = RateLimiter(max_per_minute=3)
    assert [limiter.allow("1.2.3.4", now=1000.0 + i) for i in range(3)] == [
        True, True, True]
    assert limiter.allow("1.2.3.4", now=1000.5) is False
    # Other IPs unaffected; window slides after 60s.
    assert limiter.allow("5.6.7.8", now=1000.5) is True
    assert limiter.allow("1.2.3.4", now=1070.0) is True


def test_security_headers_cover_clickjacking_and_sniffing():
    assert SECURITY_HEADERS["X-Content-Type-Options"] == "nosniff"
    assert SECURITY_HEADERS["X-Frame-Options"] == "DENY"
    assert "Content-Security-Policy" in SECURITY_HEADERS


def test_feedback_validation(tmp_path):
    path = tmp_path / "f.db"
    store.init_db(path)
    conn = store.connect(path)
    try:
        with pytest.raises(ValueError, match="must not be empty"):
            store.add_feedback(conn, change_report_id=None, contact="",
                               message="   ")
        with pytest.raises(ValueError, match="too long"):
            store.add_feedback(conn, change_report_id=None, contact="",
                               message="x" * 4001)
        fid = store.add_feedback(conn, change_report_id=None, contact="a@b",
                                 message="Title looks wrong")
        conn.commit()
        rows = store.list_feedback(conn)
        assert len(rows) == 1 and rows[0]["status"] == "open"
        store.resolve_feedback(conn, fid)
        conn.commit()
        assert store.list_feedback(conn, status="open") == []
        with pytest.raises(ValueError, match="unknown feedback"):
            store.resolve_feedback(conn, 99999)
    finally:
        conn.close()
