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
        elif self.path == "/echo-conditional":
            inm = self.headers.get("If-None-Match", "")
            ims = self.headers.get("If-Modified-Since", "")
            body = (f"If-None-Match: {inm}\n"
                    f"If-Modified-Since: {ims}\n").encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/etagged":
            if self.headers.get("If-None-Match") == '"act-1"':
                self.send_response(304)
                self.end_headers()
                return
            body = b"The Sample Act, as notified."
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("ETag", '"act-1"')
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/lastmod":
            stamp = "Wed, 21 Oct 2015 07:28:00 GMT"
            if self.headers.get("If-Modified-Since") == stamp:
                self.send_response(304)
                self.end_headers()
                return
            body = b"The Sample Act, as notified."
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Last-Modified", stamp)
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


def test_conditional_headers_sent_with_cached_validators(server):
    result = fetch_url(f"{server}/echo-conditional", ALLOW,
                       etag='"old-etag"',
                       last_modified="Mon, 01 Jan 2024 00:00:00 GMT")
    assert result.status == 200
    assert b'If-None-Match: "old-etag"' in result.data
    assert b"If-Modified-Since: Mon, 01 Jan 2024 00:00:00 GMT" in result.data


def test_no_conditional_headers_without_cached_validators(server):
    result = fetch_url(f"{server}/echo-conditional", ALLOW)
    assert result.status == 200
    assert b"If-None-Match: \n" in result.data
    assert b"If-Modified-Since: \n" in result.data


def test_validators_reported_from_response(server):
    result = fetch_url(f"{server}/etagged", ALLOW)
    assert result.status == 200
    assert result.etag == '"act-1"'
    assert result.last_modified == ""


def test_304_returns_not_modified(server):
    first = fetch_url(f"{server}/etagged", ALLOW)
    assert first.data  # sanity: first read carries the body
    second = fetch_url(f"{server}/etagged", ALLOW, etag=first.etag)
    assert second.status == 304
    assert second.not_modified is True
    assert second.data == b""


def test_last_modified_validator_304(server):
    first = fetch_url(f"{server}/lastmod", ALLOW)
    assert first.last_modified == "Wed, 21 Oct 2015 07:28:00 GMT"
    second = fetch_url(f"{server}/lastmod", ALLOW,
                       last_modified=first.last_modified)
    assert second.status == 304
    assert second.not_modified is True


def test_rate_limiter_throttles():
    limiter = RateLimiter(0.3)
    limiter.wait("h.example")
    start = time.monotonic()
    limiter.wait("h.example")
    assert time.monotonic() - start >= 0.25
