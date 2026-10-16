"""Safe HTTP fetcher (stdlib only): allowlist, timeouts, size caps, throttling.

Security rules (spec section 13):
- Only ``http``/``https`` URLs whose host is in the configured allowlist
  (derived from the source registry's official base URLs) are fetched.
- Redirects to non-allowlisted hosts are rejected — no open fetch-by-URL.
- Response sizes are capped; timeouts + retries with backoff apply.
- Per-host rate limiting is enforced in-process.
"""
from __future__ import annotations

import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

USER_AGENT = "IndiaLawRadar/0.2.0 (+local MVP; respects robots.txt and rate limits)"

MAX_REDIRECTS = 5


class FetchError(Exception):
    """Raised for any fetch failure (network, policy, size, content)."""


@dataclass
class FetchResult:
    data: bytes
    final_url: str
    status: int
    content_type: str
    host: str


class RateLimiter:
    """In-process per-host throttle."""

    def __init__(self, min_interval_seconds: float = 1.0) -> None:
        self.min_interval = max(0.0, min_interval_seconds)
        self._last: dict[str, float] = {}

    def wait(self, host: str) -> None:
        last = self._last.get(host)
        if last is not None:
            delay = self.min_interval - (time.monotonic() - last)
            if delay > 0:
                time.sleep(delay)
        self._last[host] = time.monotonic()


def _check_url(url: str, allowlist: set[str]) -> urllib.parse.ParseResult:
    try:
        parts = urllib.parse.urlparse(url)
    except ValueError as exc:
        raise FetchError(f"unparseable URL: {exc}") from exc
    if parts.scheme not in ("http", "https"):
        raise FetchError(
            f"URL scheme not allowed: {parts.scheme or '(none)'} (only http/https)"
        )
    host = (parts.hostname or "").lower()
    if not host:
        raise FetchError("URL has no host")
    if host not in allowlist:
        raise FetchError(f"host not in allowlist: {host}")
    return parts


class _GuardedRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Redirect handler that enforces the host allowlist on every hop."""

    def __init__(self, allowlist: set[str]) -> None:
        super().__init__()
        self.allowlist = allowlist

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        target = urllib.parse.urljoin(req.full_url, newurl)
        _check_url(target, self.allowlist)  # raises FetchError on violation
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_url(
    url: str,
    allowlist: set[str],
    timeout_seconds: int = 30,
    max_bytes: int = 50_000_000,
    rate_limiter: RateLimiter | None = None,
    min_interval_seconds: float = 1.0,
    max_retries: int = 3,
) -> FetchResult:
    """Fetch a URL under the allowlist policy. Raises FetchError on failure."""
    if not allowlist:
        raise FetchError("refusing to fetch: allowlist is empty")
    parts = _check_url(url, allowlist)
    host = (parts.hostname or "").lower()
    limiter = rate_limiter or RateLimiter(min_interval_seconds)
    opener = urllib.request.build_opener(_GuardedRedirectHandler(allowlist))
    last_error: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            limiter.wait(host)
            request = urllib.request.Request(
                url, headers={"User-Agent": USER_AGENT}
            )
            with opener.open(request, timeout=timeout_seconds) as response:
                status = getattr(response, "status", 200)
                final_url = response.geturl()
                # Re-validate the final URL after any redirects.
                _check_url(final_url, allowlist)
                if status >= 500:
                    raise FetchError(f"server error: HTTP {status}")
                if status >= 400:
                    raise FetchError(f"client error: HTTP {status} (no retry)")
                length = response.headers.get("Content-Length")
                if length is not None:
                    try:
                        if int(length) > max_bytes:
                            raise FetchError(
                                f"response too large: {length} bytes "
                                f"(limit {max_bytes})"
                            )
                    except ValueError:
                        pass
                chunks: list[bytes] = []
                remaining = max_bytes + 1
                while True:
                    chunk = response.read(min(65536, remaining))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    remaining -= len(chunk)
                    if remaining <= 0:
                        raise FetchError(
                            f"response exceeded size limit ({max_bytes} bytes)"
                        )
                data = b"".join(chunks)
                content_type = response.headers.get_content_type() or ""
                return FetchResult(
                    data=data,
                    final_url=final_url,
                    status=status,
                    content_type=content_type,
                    host=host,
                )
        except FetchError:
            raise  # policy errors are never retried
        except urllib.error.HTTPError as exc:
            if 500 <= (exc.code or 0) < 600 and attempt < max_retries:
                last_error = exc
                time.sleep(2 ** (attempt - 1))
                continue
            raise FetchError(f"HTTP error: {exc}") from exc
        except Exception as exc:  # noqa: BLE001 — timeouts, DNS, refused, etc.
            last_error = exc
            if attempt < max_retries:
                time.sleep(2 ** (attempt - 1))
                continue
            raise FetchError(f"fetch failed after {max_retries} attempts: {exc}") from exc
    raise FetchError(f"fetch failed: {last_error}")  # pragma: no cover
