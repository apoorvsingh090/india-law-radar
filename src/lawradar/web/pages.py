"""HTML pages (Milestone 5). All dynamic values are escaped.

Design: minimal professional editorial layout, readable legal text, clear
provenance. No external assets, no JavaScript, no "fully up to date"
badge — every page shows what is evidenced and what is unknown.
"""
from __future__ import annotations

import html
import json

APP_TITLE = "India Law Radar"

_CSS = (
    "body{font-family:Georgia,serif;max-width:56rem;margin:0 auto;padding:1rem;"
    "color:#1a1a1a;background:#fdfdfa}"
    "header{border-bottom:2px solid #1a1a1a;margin-bottom:1rem}"
    "nav a{margin-right:1rem;color:#1a4d8f}"
    "table{border-collapse:collapse;width:100%;margin:1rem 0}"
    "th,td{border:1px solid #999;padding:.4rem;text-align:left;vertical-align:top}"
    "th{background:#eee}.badge{display:inline-block;padding:.1rem .5rem;"
    "border:1px solid #666;border-radius:.5rem;font-size:.85rem}"
    ".warn{background:#fff3cd}.bad{background:#f8d7da}.ok{background:#d4edda}"
    "pre{white-space:pre-wrap;background:#f4f4f4;padding:.5rem;overflow:auto}"
    "form.inline{display:inline}input,select,textarea{font:inherit;margin:.2rem 0}"
    "footer{margin-top:2rem;border-top:1px solid #999;font-size:.85rem;color:#555}"
)


def esc(value) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def snippet_html(snippet: str) -> str:
    """Escape an FTS snippet while keeping <b> match markers."""
    out = html.escape(snippet or "")
    return out.replace("&lt;b&gt;", "<b>").replace("&lt;/b&gt;", "</b>")


def health_badge(status: str) -> str:
    cls = {"ok": "ok", "due": "warn", "stale": "bad",
           "failing": "bad"}.get(status, "")
    return (f"<span class=\"badge {cls}\">{esc(status)}</span>")


def layout(title: str, body: str) -> str:
    return (
        "<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        "<link rel=\"alternate\" type=\"application/atom+xml\" "
        "href=\"/feed.xml\" title=\"Published change reports (Atom)\">"
        f"<title>{esc(title)} — {APP_TITLE}</title>"
        f"<style>{_CSS}</style></head><body>"
        f"<header><h1>{APP_TITLE}</h1><nav>"
        "<a href=\"/\">Dashboard</a><a href=\"/changes\">Changes</a>"
        "<a href=\"/feed.xml\">Feed</a>"
        "<a href=\"/search\">Search</a><a href=\"/sources\">Sources</a>"
        "<a href=\"/review\">Review</a><a href=\"/coverage\">Coverage</a>"
        "<a href=\"/limitations\">Limitations</a>"
        "<a href=\"/feedback\">Feedback</a><a href=\"/privacy\">Privacy</a>"
        "</nav></header><main>"
        f"<h2>{esc(title)}</h2>{body}</main>"
        "<footer>India Law Radar MVP — source-verifiable drafts, not legal "
        "advice. Every claim links to its official source. "
        "Unverified means unverified.</footer></body></html>"
    )


def dashboard(ctx: dict) -> str:
    rows = []
    for source in ctx["sources"]:
        rows.append(
            f"<tr><td>{esc(source['id'])}</td>"
            f"<td>{esc(source['name'])}</td>"
            f"<td>{health_badge(source.get('status', 'unknown'))}</td>"
            f"<td>{esc(source.get('health_detail') or '—')}</td>"
            f"<td>{esc(source['last_success_at'] or '—')}</td></tr>")
    recent = "".join(
        f"<li><a href=\"/reports/{r['id']}\">{esc(r['document_title'])}</a> "
        f"<span class=\"badge\">{esc(r['change_type'])}</span> "
        f"{esc(r['verification_status'])}</li>"
        for r in ctx["recent_reports"])
    failures = "".join(
        f"<li>run {r['id']} ({esc(r['source_id'])}): {esc(r['error_summary'][:120])}</li>"
        for r in ctx["failed_runs"]) or "<li>None recorded.</li>"
    gaps = "".join(
        f"<li>{esc(g)}</li>" for g in ctx["coverage_gaps"]) or "<li>None.</li>"
    monitored = sum(1 for s in ctx["sources"] if s.get("monitored"))
    unhealthy = sum(1 for s in ctx["sources"] if not s.get("healthy", True))
    return (
        f"<p>{ctx['source_count']} configured sources · "
        f"{monitored} monitored, {unhealthy} need attention · "
        f"{ctx['pending_review']} pending reviews · "
        f"{ctx['unpublished']} unpublished reports</p>"
        "<h3>Sources</h3><table><tr><th>ID</th><th>Name</th><th>State</th>"
        "<th>Health detail</th><th>Last success</th></tr>"
        + "".join(rows) + "</table>"
        + "<h3>Recent changes</h3><ul>" + (recent or "<li>None yet.</li>") + "</ul>"
        + "<h3>Ingestion failures</h3><ul>" + failures + "</ul>"
        + "<h3>Coverage warnings</h3><ul>" + gaps + "</ul>")


def changes_feed(reports: list[dict], filters: dict,
                 options: dict) -> str:
    def _opts(name: str, values: list[str]) -> str:
        current = filters.get(name, "")
        items = ["<option value=\"\">all</option>"] + [
            f"<option value=\"{esc(v)}\"{' selected' if v == current else ''}>"
            f"{esc(v)}</option>" for v in values]
        return (f"<label>{esc(name)} <select name=\"{esc(name)}\">"
                + "".join(items) + "</select></label> ")

    form = ("<form method=\"get\" action=\"/changes\">"
            + _opts("source", options["sources"])
            + _opts("jurisdiction", options["jurisdictions"])
            + _opts("type", options["types"])
            + _opts("status", options["statuses"])
            + "<button type=\"submit\">Filter</button></form>")
    items = "".join(
        f"<li><a href=\"/reports/{r['id']}\">{esc(r['document_title'])}</a><br>"
        f"<span class=\"badge\">{esc(r['change_type'])}</span> "
        f"{esc(r['issuing_authority'] or 'unknown authority')} · "
        f"{esc(r['jurisdiction'])} · {esc(r['document_type'])} · "
        f"retrieved {esc(r['retrieved_at'] or 'unknown')} · "
        f"{esc(r['verification_status'])}"
        + (" · published" if r["published_at"] else " · unpublished")
        + f"<br>{esc((r['summary'] or '')[:300])}<br>"
        f"<a href=\"{esc(r['official_url'])}\">official source</a></li>"
        for r in reports) or "<li>No changes match.</li>"
    return form + "<ul>" + items + "</ul>"


def report_detail(report: dict, document: dict, versions: list[dict],
                   citations: list[dict], trail: list[dict],
                   token: str = "") -> str:
    claims = json.loads(report["claims_json"])
    affected = json.loads(report["affected_sections"])
    versions_html = "".join(
        f"<tr><td>v{v['version_number']}</td><td>{esc(v['content_sha256'][:16])}…</td>"
        f"<td>{esc(v['extraction_status'])}</td><td>{esc(v['review_status'])}</td>"
        f"<td>{esc(v['retrieved_at'])}</td></tr>" for v in versions)
    claims_html = "".join(
        f"<li>[{esc(c['claim_type'])}] {esc(c['claim'])}<br>"
        f"citations: {esc(', '.join(c['citation_ids']))}</li>"
        for c in claims)
    cites_html = "".join(
        f"<li>{esc(c['locator_type'])}: {esc(c['locator_value'])} "
        f"({esc(c['verification_status'])})<br>"
        f"<q>{esc(c['quoted_text'][:300])}</q> "
        f"<a href=\"{esc(c['source_url'])}\">source</a></li>"
        for c in citations) or "<li>No citations recorded.</li>"
    trail_html = "".join(
        f"<li>task {t['id']}: {esc(t['status'])} by {esc(t['reviewer'] or '—')} "
        f"— {esc(t['review_notes'] or t['reason'] or '')}</li>"
        for t in trail) or "<li>No review history yet.</li>"
    token_field = (f"<input type=\"hidden\" name=\"token\" value=\"{esc(token)}\">"
                   if token else "")
    form = (
        f"<form method=\"post\" action=\"/reports/{report['id']}/review\">"
        f"{token_field}"
        "<label>Reviewer <input name=\"reviewer\" placeholder=\"local\"></label> "
        "<label>Notes <input name=\"notes\" size=\"40\"></label><br>"
        "<button name=\"decision\" value=\"approved\" type=\"submit\">Approve</button> "
        "<button name=\"decision\" value=\"rejected\" type=\"submit\">Reject</button> "
        "<button name=\"decision\" value=\"needs_changes\" type=\"submit\">"
        "Request changes</button></form>")
    warnings: list[str] = []
    for version in versions:
        try:
            parsed = json.loads(version.get("parser_warnings") or "[]")
        except (ValueError, TypeError):
            parsed = ["unparseable parser warnings"]
        warnings.extend(str(w) for w in parsed)
    warnings_html = ("<ul>" + "".join(f"<li>{esc(w)}</li>" for w in warnings)
                     + "</ul>" if warnings else "<p>No warnings.</p>")
    return (
        f"<p><span class=\"badge\">{esc(report['change_type'])}</span> "
        f"{esc(report['verification_status'])} · "
        f"{'published ' + esc(report['published_at']) if report['published_at'] else 'unpublished'}</p>"
        f"<p><b>Document:</b> {esc(document.get('title', ''))} · "
        f"{esc(document.get('document_type', ''))} · "
        f"{esc(document.get('jurisdiction', ''))} · "
        f"{esc(document.get('issuing_authority', '') or 'unknown authority')}</p>"
        f"<p><b>Official source:</b> "
        f"<a href=\"{esc(document.get('official_url', ''))}\">"
        f"{esc(document.get('official_url', '') or 'not recorded')}</a> · "
        f"<b>Published:</b> unknown (never inferred)</p>"
        f"<p>{esc(report['summary'])}</p>"
        + (f"<p><b>Affected:</b> {esc(', '.join(affected))}</p>" if affected else "")
        + "<p><b>Commencement:</b> Not established from the extracted "
        "evidence (unverified).</p>"
        + "<h3>Warnings</h3>" + warnings_html
        + "<h3>Versions</h3><table><tr><th>Version</th><th>SHA</th>"
        "<th>Extraction</th><th>Review</th><th>Retrieved</th></tr>"
        + versions_html + "</table>"
        + "<h3>Observed facts vs interpretation</h3><ul>" + claims_html + "</ul>"
        + "<h3>Citations</h3><ul>" + cites_html + "</ul>"
        + "<h3>Audit diff</h3><pre>" + esc(report["diff_text"][:20000]) + "</pre>"
        + "<h3>Review history</h3><ul>" + trail_html + "</ul>"
        + "<h3>Human review</h3>" + form)


def document_page(document: dict, versions: list[dict],
                   reports: list[dict]) -> str:
    versions_html = "".join(
        f"<li>v{v['version_number']} — {esc(v['content_sha256'][:16])}… "
        f"({esc(v['extraction_status'])}, retrieved {esc(v['retrieved_at'])})</li>"
        for v in versions)
    reports_html = "".join(
        f"<li><a href=\"/reports/{r['id']}\">report {r['id']}</a> "
        f"{esc(r['change_type'])} ({esc(r['verification_status'])})</li>"
        for r in reports) or "<li>No reports yet.</li>"
    return (
        f"<p>{esc(document['document_type'])} · {esc(document['jurisdiction'])} · "
        f"{esc(document['issuing_authority'] or 'unknown authority')}</p>"
        f"<p><a href=\"{esc(document['official_url'])}\">official source</a></p>"
        + "<h3>Versions</h3><ul>" + versions_html + "</ul>"
        + "<h3>Reports</h3><ul>" + reports_html + "</ul>")


def search_page(query: str, results: list[dict], doc_lookup) -> str:
    form = (f"<form method=\"get\" action=\"/search\">"
            f"<input name=\"q\" value=\"{esc(query)}\" size=\"40\"> "
            "<button type=\"submit\">Search</button></form>")
    if not query:
        return form + "<p>Search titles and extracted legal text.</p>"
    items = "".join(
        f"<li><a href=\"/documents/{r['doc_id']}\">{esc(r['title'])}</a><br>"
        f"{snippet_html(r['snippet'])} "
        f"<a href=\"{esc(doc_lookup(r['doc_id']))}\">official source</a></li>"
        for r in results) or "<li>No matches.</li>"
    return form + f"<p>{len(results)} result(s) for {esc(query)!r}.</p><ul>" + items + "</ul>"


def sources_page(sources: list[dict]) -> str:
    rows = "".join(
        f"<tr><td>{esc(s['id'])}</td><td>{esc(s['name'])}</td>"
        f"<td><a href=\"{esc(s['base_url'])}\">{esc(s['base_url'])}</a></td>"
        f"<td>{esc(s['access_method'])}</td><td>{esc(s['jurisdiction'])}</td>"
        f"<td>{'yes' if s['enabled'] else 'no'}</td>"
        f"<td>{health_badge(s.get('status', 'unknown'))}</td>"
        f"<td>{esc(s.get('next_due_at') or '—')}</td>"
        f"<td>{esc(s.get('health_detail') or '—')}</td>"
        f"<td>{esc(s['terms_review_status'])}</td>"
        f"<td>{esc(s['last_checked_at'] or '—')}</td>"
        f"<td>{esc(s['last_success_at'] or '—')}</td>"
        f"<td>{esc(s['last_error'] or '—')}</td>"
        f"<td>{esc(s['coverage_notes'])}</td></tr>"
        for s in sources)
    return ("<table><tr><th>ID</th><th>Name</th><th>Base URL</th><th>Method</th>"
            "<th>Jurisdiction</th><th>Enabled</th><th>Status</th>"
            "<th>Next due</th><th>Health detail</th><th>Terms</th>"
            "<th>Last check</th><th>Last success</th><th>Error</th>"
            "<th>Coverage</th></tr>" + rows + "</table>")


def review_page(tasks: list[dict], token: str = "") -> str:
    token_field = (f"<input type=\"hidden\" name=\"token\" value=\"{esc(token)}\">"
                   if token else "")
    items = "".join(
        f"<li>task {t['id']}: <a href=\"/reports/{t['change_report_id']}\">"
        f"report {t['change_report_id']}</a> "
        f"<span class=\"badge warn\">{esc(t['severity'])}</span><br>"
        f"{esc(t['reason'])}"
        f"<form class=\"inline\" method=\"post\" "
        f"action=\"/reports/{t['change_report_id']}/review\">{token_field}"
        "<input type=\"hidden\" name=\"reviewer\" value=\"web\">"
        "<input name=\"notes\" placeholder=\"notes (required to reject)\"> "
        "<button name=\"decision\" value=\"approved\">Approve</button> "
        "<button name=\"decision\" value=\"rejected\">Reject</button> "
        "<button name=\"decision\" value=\"needs_changes\">Request changes</button>"
        "</form></li>"
        for t in tasks) or "<li>Queue is empty. Nothing needs review.</li>"
    return "<ul>" + items + "</ul>"


def coverage_page(ctx: dict) -> str:
    monitored = "".join(
        f"<li>{esc(s['id'])} — {esc(s['name'])} "
        f"(terms: {esc(s['terms_review_status'])})</li>"
        for s in ctx["sources"]) or "<li>No sources configured.</li>"
    gaps = "".join(f"<li>{esc(g)}</li>" for g in ctx["gaps"]) or "<li>None.</li>"
    return (
        "<h3>Sources currently monitored</h3><ul>" + monitored + "</ul>"
        f"<p>Ingestion runs recorded: {ctx['run_count']}. "
        f"Last successful ingestion: {esc(ctx['last_success'] or 'never')}.</p>"
        "<h3>Known gaps</h3><ul>" + gaps + "</ul>"
        "<h3>AI summaries</h3><p>Draft summaries are deterministic unless an "
        "operator explicitly configures a local model command; all drafts "
        "require human review before publication.</p>"
        "<h3>Limitations</h3><p>No claim of completeness or currency. "
        "Presence in this database does not mean a provision is in force. "
        "This tool is not a substitute for a qualified advocate. "
        "Full statement: <a href=\"/limitations\">Limitations</a>.</p>"
        "<h3>Report an error</h3><p>Use <a href=\"/feedback\">Feedback</a> "
        "with the source URL and retrieval timestamp shown on the report "
        "page.</p>")


def not_found(path: str) -> str:
    return f"<p>No page for {esc(path)}. <a href=\"/\">Back to dashboard</a>.</p>"


def feedback_page(report_id: str = "") -> str:
    return (
        "<p>Found a wrong title, date, citation, or link? Tell us - error "
        "reports linked to a report automatically join the human review "
        "queue.</p>"
        "<form method=\"post\" action=\"/feedback\">"
        f"<label>Report id (optional) <input name=\"report_id\" "
        f"value=\"{esc(report_id)}\"></label><br>"
        "<label>Contact (optional) <input name=\"contact\"></label><br>"
        "<label>What is wrong?<br><textarea name=\"message\" rows=\"5\" "
        "cols=\"60\" required></textarea></label><br>"
        "<button type=\"submit\">Send feedback</button></form>")


def privacy_page() -> str:
    return (
        "<h3>What we collect</h3>"
        "<p>Nothing by default. No accounts, no analytics, no trackers, no "
        "cookies. The web UI serves pages; it does not phone home.</p>"
        "<h3>What operators store</h3>"
        "<p>Official legal documents the operator ingests (URL, retrieval "
        "time, hash, text), derived reports, review decisions, and any "
        "feedback visitors submit (message + optional contact). All of it "
        "lives in the operator's local SQLite file — see "
        "<a href=\"/coverage\">Coverage</a> for what is monitored.</p>"
        "<h3>What we never do</h3>"
        "<p>No personal data is required to read anything. Do not submit "
        "client confidences or personal documents through the feedback form. "
        "Before adding accounts or uploads, review applicable privacy and "
        "data-protection requirements.</p>")


def limitations_page() -> str:
    return (
        "<h3>Coverage</h3><p>Only the sources listed under "
        "<a href=\"/sources\">Sources</a> are monitored, and only from the "
        "dates actually ingested. This database is not complete and is "
        "never claimed to be current.</p>"
        "<h3>Status</h3><p>Presence here does not mean a provision is in "
        "force. Publication, commencement, and applicability are different "
        "dates; anything not evidenced is shown as unverified or unknown.</p>"
        "<h3>Machine output</h3><p>Draft summaries are labelled as drafts. "
        "Unpublished reports are not legal conclusions. Nothing here is a "
        "substitute for a qualified advocate.</p>"
        "<h3>Corrections</h3><p>Use <a href=\"/feedback\">Feedback</a> to "
        "report an error; corrections are reviewed against the official "
        "source with full history preserved.</p>")


def review_result(report_id: int, outcome: dict) -> str:
    return (f"<p>Report {report_id}: {esc(outcome['decision'])} "
            f"by {esc(outcome['reviewer'])}.</p>"
            f"<p><a href=\"/reports/{report_id}\">Back to report</a> · "
            f"<a href=\"/review\">Back to queue</a>.</p>")
