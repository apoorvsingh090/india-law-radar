"""Fetcher tests: allowlist enforcement, redirects, size caps, retries."""
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from lawradar.ingestion.fetcher import FetchError, RateLimiter, fetch_url


class _Handler(BaseHTTPRequestHandler):
    calls = {"flaky": 0}

    def log_message(self, *args):  # noqa: ANN001 — silence test server logs
        pass

    def do_GET(self):  # noqa: N802
        if self.path == "/ok":
            body = b"<html><body>hello official source</body></html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/big":
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", "1000000")
            self.end_headers()
        elif self.path == "/redir-evil":
            self.send_response(302)
            self.send_header("Location", "http://evil.invalid/stolen")
            self.end_headers()
        elif self.path == "/redir-local":
            self.send_response(302)
            self.send_header("Location", "/ok")
            self.end_headers()
        elif self.path == "/flaky":
            type(self).calls["flaky"] += 1
            if type(self).calls["flaky"] == 1:
                self.send_response(500)
                self.end_headers()
            else:
                body = b"recovered"
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()


@pytest.fixture()
def server():
    httpd = HTTPServer(("127.0.0.1", 0), _Handler)
    _Handler.calls["flaky"] = 0
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()


ALLOW = {"127.0.0.1"}


def test_ok_fetch(server):
    result = fetch_url(f"{server}/ok", ALLOW, max_bytes=100000)
    assert result.status == 200
    assert b"hello official source" in result.data
    assert result.content_type == "text/html"


def test_non_allowlisted_host_rejected():
    with pytest.raises(FetchError, match="not in allowlist"):
        fetch_url("http://evil.invalid/x", ALLOW)


def test_non_http_scheme_rejected():
    with pytest.raises(FetchError, match="scheme"):
        fetch_url("file:///etc/passwd", ALLOW)
    with pytest.raises(FetchError, match="scheme"):
        fetch_url("ftp://127.0.0.1/x", ALLOW)


def test_empty_allowlist_refuses_everything(server):
    with pytest.raises(FetchError, match="allowlist is empty"):
        fetch_url(f"{server}/ok", set())


def test_redirect_to_evil_rejected(server):
    with pytest.raises(FetchError, match="not in allowlist"):
        fetch_url(f"{server}/redir-evil", ALLOW)


def test_redirect_within_allowlist_ok(server):
    result = fetch_url(f"{server}/redir-local", ALLOW)
    assert result.status == 200
    assert result.final_url.endswith("/ok")


def test_oversize_response_rejected(server):
    with pytest.raises(FetchError, match="too large"):
        fetch_url(f"{server}/big", ALLOW, max_bytes=1000)


def test_500_retried_then_succeeds(server):
    result = fetch_url(f"{server}/flaky", ALLOW)
    assert result.data == b"recovered"


def test_rate_limiter_throttles():
    limiter = RateLimiter(0.3)
    limiter.wait("h.example")
    start = time.monotonic()
    limiter.wait("h.example")
    assert time.monotonic() - start >= 0.25
