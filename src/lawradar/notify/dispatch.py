"""Outbound webhook dispatch for approved reports (Milestone 11).

Publication stays exclusively a human approval; this module only fans a
deterministic JSON payload out to explicitly configured webhook URLs
after that approval has committed. Core invariants:

* Approval can never block or fail because of delivery - per-target
  errors are contained and recorded as ``notification_attempts`` rows.
* Delivery is at most once per (report, webhook); the partial unique
  index (migration 006) fail-closes against duplicate sends.
* No automatic retries. ``lawradar notify send`` is the explicit,
  idempotent retry path. Failures surface in the web UI and CLI.
* Only ``http``/``https`` targets are accepted; secrets live in the
  operator's local, git-ignored settings YAML.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from lawradar import __version__
from lawradar.db import store

RESPONSE_CAP = 2000
DEFAULT_TIMEOUT_SECONDS = 10.0
USER_AGENT = f"IndiaLawRadar/{__version__} (webhook-dispatch)"


class NotifyError(ValueError):
    """Configuration or payload problem - nothing was sent."""


@dataclass(frozen=True)
class NotifyTarget:
    name: str
    url: str
    secret: str = ""
    enabled: bool = True

    def to_dict(self) -> dict:
        return {"name": self.name, "url": self.url,
                "secret": bool(self.secret), "enabled": self.enabled}


def targets_from_config(config) -> list[NotifyTarget]:
    """Validated webhook targets from settings (raises on config errors)."""
    raw = getattr(config, "notify_webhooks", []) or []
    targets: list[NotifyTarget] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise NotifyError(
                f"notify_webhooks[{index}] must be a mapping with 'url'")
        url = str(item.get("url", "")).strip()
        if not url:
            raise NotifyError(f"notify_webhooks[{index}] is missing 'url'")
        if not url.startswith(("http://", "https://")):
            raise NotifyError(
                f"notify_webhooks[{index}] URL must start with "
                "http:// or https://")
        name = str(item.get("name", "")).strip() or f"webhook-{index + 1}"
        secret = str(item.get("secret", ""))
        enabled = item.get("enabled", True)
        if isinstance(enabled, str):
            enabled = enabled.strip().lower() in ("1", "true", "yes", "on")
        targets.append(NotifyTarget(name=name, url=url, secret=secret,
                                    enabled=bool(enabled)))
    if len({t.name for t in targets}) != len(targets):
        raise NotifyError("notify_webhooks names must be unique")
    return targets


def signature_headers(target: NotifyTarget, body: bytes,
                      timestamp: int | None = None) -> dict[str, str]:
    """HMAC signing headers for receivers that verify authenticity.

    Format: ``X-LawRadar-Token: t=<unix ts>,v1=<hex>`` with
    ``v1 = HMAC-SHA256(secret, b"<ts>." + body)``.
    """
    if not target.secret:
        return {}
    ts = int(time.time() if timestamp is None else timestamp)
    signed = f"{ts}.".encode() + body
    digest = hmac.new(target.secret.encode(), signed,
                      hashlib.sha256).hexdigest()
    return {"X-LawRadar-Token": f"t={ts},v1={digest}"}


def build_payload(report: dict, document: dict) -> dict:
    """Deterministic, minimal public payload for an approved report."""
    affected = report.get("affected_sections") or "[]"
    if isinstance(affected, str):
        try:
            affected = json.loads(affected)
        except (TypeError, ValueError):
            affected = ["unparseable affected_sections"]
    return {
        "event": "report.approved",
        "app": "india-law-radar",
        "version": __version__,
        "report_id": report["id"],
        "document_id": report.get("document_id"),
        "document_title": (report.get("document_title")
                           or document.get("title", "")),
        "change_type": report.get("change_type", "unknown"),
        "summary": report.get("summary", ""),
        "affected_sections": affected,
        "jurisdiction": document.get("jurisdiction", "unknown"),
        "official_url": document.get("official_url", ""),
        "published_at": report.get("published_at") or "",
        "verification_status": report.get("verification_status",
                                          "approved"),
    }


def post_webhook(target: NotifyTarget, body: bytes,
                 timeout: float) -> tuple[int, str]:
    """Blocking POST. Returns (http_status, snippet); raises NotifyError on
    network failure. HTTP-level errors (4xx/5xx) are normal returns so the
    caller records the status as a failed attempt."""
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "User-Agent": USER_AGENT,
        "X-LawRadar-Event": "report.approved",
        "X-LawRadar-Delivery": uuid.uuid4().hex,
    }
    headers.update(signature_headers(target, body))
    request = Request(target.url, data=body, method="POST")
    for key, value in headers.items():
        request.add_header(key, value)
    try:
        with urlopen(request, timeout=timeout) as response:
            snippet = response.read(RESPONSE_CAP).decode("utf-8", "replace")
            return int(response.status), snippet
    except HTTPError as exc:
        try:
            snippet = exc.read(RESPONSE_CAP).decode("utf-8", "replace")
        except OSError:  # pragma: no cover - body unreadable
            snippet = ""
        return int(exc.code), snippet
    except (URLError, OSError) as exc:
        raise NotifyError(str(exc)) from exc


def dispatch_report(conn, config, report_id: int,
                    *, poster=None) -> list[dict]:
    """Deliver one published report to every pending configured target.

    Idempotent: targets already delivered for this report are skipped and
    reported as ``deduplicated``; disabled targets report ``disabled``.
    Per-target errors never propagate - each lands in
    ``notification_attempts`` and the outcome list.
    """
    targets = targets_from_config(config)
    if not targets:
        return []
    send = poster or post_webhook
    timeout = float(getattr(config, "notify_timeout_seconds",
                            DEFAULT_TIMEOUT_SECONDS))
    report_row = store.get_report(conn, report_id)
    if report_row is None:
        raise NotifyError(f"unknown report id {report_id}")
    report = dict(report_row)
    if not report.get("published_at"):
        raise NotifyError(
            f"report {report_id} is not published; dispatch follows "
            "approval only")
    document = store.get_document(conn, report["document_id"])
    body = json.dumps(build_payload(report, dict(document) if document
                                    else {}), sort_keys=True)
    body = body.encode("utf-8")
    already = store.delivered_webhooks(conn, report_id)
    outcomes: list[dict] = []
    for target in targets:
        if not target.enabled:
            outcomes.append({"webhook": target.name, "status": "disabled"})
            continue
        if target.name in already:
            outcomes.append({"webhook": target.name,
                             "status": "deduplicated"})
            continue
        status, http_status, snippet, error = "failed", None, "", ""
        try:
            http_status, snippet = send(target, body, timeout)
            if 200 <= http_status < 300:
                status = "delivered"
            else:
                error = f"HTTP {http_status}"
        except NotifyError as exc:
            error = str(exc)
        store.record_notification_attempt(
            conn, change_report_id=report_id, webhook=target.name,
            url=target.url, status=status, http_status=http_status,
            response_snippet=snippet[:RESPONSE_CAP], error=error)
        conn.commit()
        outcomes.append({"webhook": target.name, "status": status,
                         "http_status": http_status, "error": error})
    return outcomes


def dispatch_pending(conn, config, report_id: int | None = None,
                     limit: int = 50, *, poster=None) -> list[dict]:
    """Retry path: deliver every published report still missing a target.

    Idempotent end to end - already-delivered targets are skipped, so a
    rerun only sends what is actually outstanding.
    """
    if report_id is not None:
        return dispatch_report(conn, config, report_id, poster=poster)
    targets = targets_from_config(config)
    names = {t.name for t in targets}
    outcomes: list[dict] = []
    for row in store.list_published_reports(conn, limit=limit):
        if names and names.issubset(
                store.delivered_webhooks(conn, row["id"])):
            continue
        outcomes.extend(dispatch_report(conn, config, row["id"],
                                        poster=poster))
    return outcomes


def after_approval(config, conn, report_id: int) -> list[dict]:
    """Fire-and-forget call after a human approval commits. Never raises.

    Disabled or unconfigured setups are a no-op. The approval itself
    happened in ``review.queue.resolve`` before this runs, so a delivery
    problem can never roll a publication back.
    """
    if not getattr(config, "notify_enabled", False):
        return []
    try:
        if not targets_from_config(config):
            return []
    except NotifyError as exc:
        # Config errors surface but must not roll back the approval.
        return [{"webhook": "config", "status": "failed",
                 "error": str(exc)[:200]}]
    try:
        return dispatch_report(conn, config, report_id)
    except Exception as exc:  # noqa: BLE001 - never block approval flow
        return [{"webhook": "dispatch", "status": "failed",
                 "error": str(exc)[:200]}]
