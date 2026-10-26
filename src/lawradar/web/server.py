"""Stdlib web server (Milestone 8): no new dependencies.

Serves the dashboard, change feed, report detail, search, source
registry, review queue, coverage/privacy/limitations pages, feedback
form, plus a small JSON API. State-changing POSTs are same-origin forms
gated by an optional shared-secret token and a per-IP rate limit; bind
defaults to loopback and non-loopback binds require --token.
"""
from __future__ import annotations

import hmac
import json
import re
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from lawradar.db import store
from lawradar.search import fts as search_fts
from lawradar.web import feeds, pages

MAX_POST_BYTES = 1_000_000

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "default-src 'self'; style-src 'unsafe-inline'",
}


class RateLimiter:
    """Fixed-window per-IP counter for state-changing requests."""

    def __init__(self, max_per_minute: int = 30) -> None:
        self.max_per_minute = max(1, max_per_minute)
        self._hits: dict[str, list[float]] = {}

    def allow(self, ip: str, now: float | None = None) -> bool:
        moment = now if now is not None else time.monotonic()
        window = [t for t in self._hits.get(ip, []) if moment - t < 60.0]
        if len(window) >= self.max_per_minute:
            self._hits[ip] = window
            return False
        window.append(moment)
        self._hits[ip] = window
        return True


class Handler(BaseHTTPRequestHandler):
    server_version = "IndiaLawRadar/0.8.0"

    # -- helpers ---------------------------------------------------------
    def _db(self):
        conn = store.connect(self.server.db_path)
        store.apply_migrations(conn)
        return conn

    def _send(self, code: int, body: str, ctype: str = "text/html; charset=utf-8",
              headers: dict | None = None) -> None:
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        for key, value in SECURITY_HEADERS.items():
            self.send_header(key, value)
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(data)

    def _page(self, title: str, body: str, code: int = 200) -> None:
        self._send(code, pages.layout(title, body))

    def _json(self, payload, code: int = 200) -> None:
        self._send(code, json.dumps(payload, indent=2, default=str),
                   "application/json; charset=utf-8")

    def _redirect(self, location: str) -> None:
        self._send(303, f"<a href=\"{location}\">continue</a>",
                   headers={"Location": location})

    def log_message(self, *args) -> None:  # noqa: ANN001 — quieter logs
        pass

    # -- GET -------------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802
        try:
            parsed = urllib.parse.urlparse(self.path)
            path, query = parsed.path, urllib.parse.parse_qs(parsed.query)
            conn = self._db()
            try:
                if path == "/":
                    self._dashboard(conn)
                elif path == "/changes":
                    self._changes(conn, query)
                elif path == "/search":
                    self._search(conn, query.get("q", [""])[0])
                elif path == "/sources":
                    rows = store.list_sources(conn)
                    self._page("Sources",
                               pages.sources_page([dict(r) for r in rows]))
                elif path == "/review":
                    tasks = store.list_review_tasks(conn, status="pending")
                    self._page("Review queue",
                               pages.review_page([dict(t) for t in tasks],
                                                 self._token_value(query)))
                elif path == "/coverage":
                    self._coverage(conn)
                elif path == "/privacy":
                    self._page("Privacy", pages.privacy_page())
                elif path == "/limitations":
                    self._page("Limitations", pages.limitations_page())
                elif path == "/feedback":
                    self._page("Report an error",
                               pages.feedback_page(
                                   report_id=query.get("report", [""])[0],
                                   token=self._token_value(query)))
                elif path == "/health":
                    self._json({"status": "ok", "version": "0.8.0"})
                elif path == "/feed.xml":
                    # Published-only Atom feed (M8): the review gate, not
                    # ingestion, decides what appears here.
                    rows = [dict(r) for r in
                            store.list_published_reports(conn, limit=50)]
                    self._send(200, feeds.atom_feed(rows),
                               "application/atom+xml; charset=utf-8")
                elif path == "/api/sources":
                    self._json([dict(r) for r in store.list_sources(conn)])
                elif path == "/api/reports":
                    doc = query.get("document", [None])[0]
                    try:
                        doc_id = int(doc) if doc else None
                    except (TypeError, ValueError):
                        self._json({"error": "document must be an integer"},
                                   400)
                        return
                    rows = store.list_reports(conn, limit=50,
                                              document_id=doc_id)
                    self._json([dict(r) for r in rows])
                elif path == "/api/search":
                    self._json(search_fts.search(
                        conn, query.get("q", [""])[0]))
                elif (match := re.fullmatch(r"/reports/(\d+)", path)):
                    self._report(conn, int(match.group(1)), query)
                elif (match := re.fullmatch(r"/api/reports/(\d+)", path)):
                    self._api_report(conn, int(match.group(1)))
                elif (match := re.fullmatch(r"/documents/(\d+)", path)):
                    self._document(conn, int(match.group(1)))
                else:
                    self._page("Not found", pages.not_found(path), 404)
            finally:
                conn.close()
        except BrokenPipeError:
            pass
        except Exception as exc:  # noqa: BLE001 — never leak tracebacks
            self._page("Error",
                       f"<p class=\"badge bad\">Something went wrong: "
                       f"{pages.esc(str(exc)[:200])}</p>", 500)

    def _token_value(self, query: dict) -> str:
        if not getattr(self.server, "token", ""):
            return ""
        return query.get("token", [""])[0]

    def _dashboard(self, conn) -> None:
        sources = [dict(r) for r in store.list_sources(conn)]
        reports = [dict(r) for r in store.list_reports(conn, limit=5)]
        pending = store.count_review_tasks_by_status(conn).get("pending", 0)
        runs = [dict(r) for r in store.latest_runs(conn, limit=20)]
        failed = [r for r in runs if r["status"] in ("failed", "partial")]
        gaps = [f"{s['id']}: {s['coverage_notes'] or 'no coverage notes'}"
                for s in sources if not s["enabled"]
                or s["terms_review_status"] == "not_reviewed"]
        unpublished = sum(1 for r in store.list_reports(conn, limit=1000)
                          if not r["published_at"])
        self._page("Dashboard", pages.dashboard({
            "sources": sources, "source_count": len(sources),
            "recent_reports": reports, "pending_review": pending,
            "failed_runs": failed, "coverage_gaps": gaps,
            "unpublished": unpublished}))

    def _changes(self, conn, query: dict) -> None:
        filt = {k: query.get(k, [""])[0]
                for k in ("source", "jurisdiction", "type", "status")}
        reports = [dict(r) for r in store.list_reports_filtered(
            conn, source=filt["source"] or None,
            jurisdiction=filt["jurisdiction"] or None,
            doc_type=filt["type"] or None,
            verification=filt["status"] or None, limit=100)]
        for report in reports:
            document = store.get_document(conn, report["document_id"])
            report["issuing_authority"] = document["issuing_authority"] or ""
            report["jurisdiction"] = document["jurisdiction"] or "unknown"
            report["document_type"] = document["document_type"] or "unknown"
            report["official_url"] = document["official_url"] or ""
            report["retrieved_at"] = self._retrieved(conn, report)
        docs = [dict(r) for r in store.list_documents(conn, limit=1000)]
        options = {
            "sources": sorted({d["source_id"] for d in docs}),
            "jurisdictions": sorted({d["jurisdiction"] or "unknown"
                                     for d in docs}),
            "types": sorted({d["document_type"] or "unknown" for d in docs}),
            "statuses": ["unverified", "citation_checked", "approved",
                         "rejected", "needs_changes"],
        }
        self._page("Changes", pages.changes_feed(reports, filt, options))

    def _retrieved(self, conn, report: dict) -> str:
        row = conn.execute(
            "SELECT retrieved_at FROM document_versions WHERE id=?",
            (report["new_version_id"],)).fetchone()
        return row["retrieved_at"] if row else ""

    def _report(self, conn, report_id: int, query: dict) -> None:
        report = store.get_report(conn, report_id)
        if report is None:
            self._page("Not found", pages.not_found(f"/reports/{report_id}"),
                       404)
            return
        report = dict(report)
        versions = [dict(v) for v in
                    store.list_versions(conn, report["document_id"])]
        citations = [dict(c) for c in
                     store.list_citations(conn, report_id)]
        document = store.get_document(conn, report["document_id"])
        from lawradar.review.queue import audit_trail

        self._page(f"Report {report_id}",
                   pages.report_detail(report, dict(document) if document else {},
                                        versions, citations,
                                        audit_trail(conn, report_id),
                                        self._token_value(query)))

    def _api_report(self, conn, report_id: int) -> None:
        report = store.get_report(conn, report_id)
        if report is None:
            self._json({"error": "not found"}, 404)
            return
        payload = dict(report)
        payload["citations"] = [dict(c) for c in
                                store.list_citations(conn, report_id)]
        self._json(payload)

    def _document(self, conn, document_id: int) -> None:
        document = store.get_document(conn, document_id)
        if document is None:
            self._page("Not found",
                       pages.not_found(f"/documents/{document_id}"), 404)
            return
        versions = [dict(v) for v in
                    store.list_versions(conn, document_id)]
        reports = [dict(r) for r in
                   store.list_reports(conn, limit=50, document_id=document_id)]
        self._page(document["title"],
                   pages.document_page(dict(document), versions, reports))

    def _search(self, conn, query_text: str) -> None:
        search_fts.ensure_indexed(conn)
        results = search_fts.search(conn, query_text) if query_text else []

        def _official(doc_id: int) -> str:
            document = store.get_document(conn, doc_id)
            return (document["official_url"] or "") if document else ""

        for result in results:
            result["doc_id"] = result.pop("id")
        self._page("Search", pages.search_page(query_text, results, _official))

    def _coverage(self, conn) -> None:
        sources = [dict(r) for r in store.list_sources(conn)]
        runs = store.latest_runs(conn, limit=1000)
        success = [r["finished_at"] for r in runs
                   if r["status"] == "success" and r["finished_at"]]
        gaps = [f"{s['id']}: {s['coverage_notes'] or 'no coverage notes'}"
                for s in sources if not s["enabled"]
                or s["terms_review_status"] == "not_reviewed"]
        self._page("Coverage", pages.coverage_page({
            "sources": sources, "run_count": len(runs),
            "last_success": max(success) if success else "",
            "gaps": gaps}))

    # -- POST ------------------------------------------------------------
    def _client_ip(self) -> str:
        return self.client_address[0] if self.client_address else "?"

    def _check_rate_limit(self) -> bool:
        limiter = getattr(self.server, "rate_limiter", None)
        if limiter is None:
            return True
        return limiter.allow(self._client_ip())

    def _read_form(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_POST_BYTES:
            self._page("Error", "<p>Form too large.</p>", 413)
            return None
        body = self.rfile.read(length).decode("utf-8", "replace")
        return urllib.parse.parse_qs(body)

    def _check_token(self, form: dict) -> bool:
        token = getattr(self.server, "token", "")
        if token and not hmac.compare_digest(
                form.get("token", [""])[0], token):
            self._page("Forbidden",
                       "<p>Missing or invalid review token.</p>", 403)
            return False
        return True

    def do_POST(self) -> None:  # noqa: N802
        try:
            parsed = urllib.parse.urlparse(self.path)
            review_match = re.fullmatch(r"/reports/(\d+)/review", parsed.path)
            if parsed.path == "/feedback":
                self._post_feedback()
                return
            if not review_match:
                self._page("Not found", pages.not_found(parsed.path), 404)
                return
            if not self._check_rate_limit():
                self._page("Too many requests",
                           "<p>Rate limit exceeded. Wait a minute and retry.</p>",
                           429)
                return
            form = self._read_form()
            if form is None:
                return
            if not self._check_token(form):
                return
            decision = form.get("decision", [""])[0]
            mapping = {"approved": "approved", "rejected": "rejected",
                       "needs_changes": "needs_changes"}
            if decision not in mapping:
                self._page("Error", "<p>Choose approve, reject, or "
                                     "request-changes.</p>", 400)
                return
            from lawradar.review.queue import resolve

            conn = self._db()
            report_id = int(review_match.group(1))
            try:
                try:
                    resolve(
                        conn, report_id=report_id,
                        decision=mapping[decision],
                        reviewer=form.get("reviewer", [""])[0],
                        notes=form.get("notes", [""])[0])
                except Exception as exc:  # noqa: BLE001 — user-facing error
                    conn.close()
                    self._page("Review refused",
                               f"<p>{pages.esc(str(exc)[:300])}</p>"
                               f"<p><a href=\"/reports/{report_id}\">"
                               f"Back to report</a>.</p>", 400)
                    return
            finally:
                conn.close()
            self._redirect(f"/reports/{report_id}")
        except BrokenPipeError:
            pass
        except Exception as exc:  # noqa: BLE001
            self._page("Error",
                       f"<p class=\"badge bad\">Something went wrong: "
                       f"{pages.esc(str(exc)[:200])}</p>", 500)

    def _post_feedback(self) -> None:
        """Accept an error report; link it to a report when given."""
        if not self._check_rate_limit():
            self._page("Too many requests",
                       "<p>Rate limit exceeded. Wait a minute and retry.</p>",
                       429)
            return
        form = self._read_form()
        if form is None:
            return
        if not self._check_token(form):
            return
        raw_report = form.get("report_id", [""])[0].strip()
        try:
            report_id = int(raw_report) if raw_report else None
        except (TypeError, ValueError):
            self._page("Error", "<p>Report id must be a number.</p>", 400)
            return
        message = form.get("message", [""])[0]
        contact = form.get("contact", [""])[0]
        conn = self._db()
        try:
            if report_id is not None and store.get_report(conn, report_id) is None:
                self._page("Error",
                            f"<p>No report {pages.esc(raw_report)}.</p>", 400)
                return
            feedback_id = store.add_feedback(
                conn, change_report_id=report_id, contact=contact,
                message=message)
            if report_id is not None:
                from lawradar.review.queue import ensure_task

                report = store.get_report(conn, report_id)
                ensure_task(
                    conn, report_id=report_id,
                    document_version_id=report["new_version_id"],
                    reason=f"user-reported error (feedback #{feedback_id}): "
                           f"{message[:200]}",
                    severity="medium")
            conn.commit()
        except ValueError as exc:
            self._page("Error", f"<p>{pages.esc(str(exc)[:300])}</p>", 400)
            return
        finally:
            conn.close()
        self._page("Thank you",
                   f"<p>Feedback #{feedback_id} recorded. A maintainer "
                   f"reviews error reports against the official source.</p>"
                   f"<p><a href=\"/\">Back to dashboard</a>.</p>")


def build_server(db_path: str = "data/lawradar.db", host: str = "127.0.0.1",
                 port: int = 8080, token: str = "",
                 post_limit_per_minute: int = 30) -> ThreadingHTTPServer:
    """Create (but do not start) the web server."""
    server = ThreadingHTTPServer((host, port), Handler)
    server.db_path = db_path
    server.token = token or ""
    server.rate_limiter = RateLimiter(post_limit_per_minute)
    server.daemon_threads = True
    return server


def serve_forever(db_path: str = "data/lawradar.db", host: str = "127.0.0.1",
                  port: int = 8080, token: str = "",
                  post_limit_per_minute: int = 30) -> None:
    """Block serving until interrupted."""
    server = build_server(db_path, host, port, token, post_limit_per_minute)
    address = f"http://{server.server_address[0]}:{server.server_address[1]}"
    print(f"Serving {pages.APP_TITLE} at {address} (Ctrl-C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
