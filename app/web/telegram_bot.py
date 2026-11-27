"""Telegram webhook: lets me start a scan or ask for a status from the chat.

Telegram calls POST /telegram/webhook for every message sent to the bot. Only my
chat id is answered, and the request must carry the secret set in setWebhook.
"""
import hmac

import httpx
import logging
import threading
from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))

from fastapi import APIRouter, Request
from sqlalchemy import func, select

from app.config import get_settings
from app.db import session_scope
from app.filters import get_setting
from app.models import Application, Job, SearchProfile
from app.notify.telegram import send_message

log = logging.getLogger(__name__)
router = APIRouter()

_run_lock = threading.Lock()

HELP = (
    "<b>AI Job Hunter</b>\n"
    "run now: search LinkedIn right away\n"
    "status: what the bot found today\n\n"
    "A scan also runs on its own every 10 minutes."
)


def _command(text: str) -> str:
    t = text.strip().lower().lstrip("/").split("@")[0]
    if t in ("run", "run now", "runnow", "scan", "fetch"):
        return "run"
    if t in ("status", "stats"):
        return "status"
    return "help"


def _scan(notify: bool) -> None:
    from app.pipeline import run_once

    try:
        stats = run_once(source="telegram" if notify else "cron")
        if not notify:
            return
        from app.pipeline import summary_text

        send_message(summary_text(stats))
    except Exception:
        log.exception("scan failed")
        if notify:
            send_message("Scan failed. Check the server logs.")
    finally:
        _run_lock.release()


def dispatch_to_github(notify: bool) -> bool:
    """Ask GitHub Actions to run the scan workflow. True if GitHub accepted it."""
    s = get_settings()
    url = f"https://api.github.com/repos/{s.github_repo}/actions/workflows/{s.scan_workflow_file}/dispatches"
    body = {"ref": "main", "inputs": {"source": "telegram" if notify else "cron",
                                      "notify_summary": "true" if notify else "false"}}
    try:
        r = httpx.post(url, json=body, timeout=20, headers={
            "Authorization": f"Bearer {s.github_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        })
    except httpx.HTTPError as e:
        log.warning("GitHub dispatch failed: %s", e)
        return False
    if r.status_code != 204:
        log.warning("GitHub dispatch returned HTTP %d: %s", r.status_code, r.text[:200])
        return False
    return True


def start_scan(notify: bool = True) -> bool:
    """Start a scan: on GitHub Actions when a token is set, otherwise in a background
    thread here. False if it could not start (already running, or GitHub refused).
    notify=False is for the timer: only new jobs are messaged, no summary."""
    if get_settings().github_token:
        return dispatch_to_github(notify)
    if not _run_lock.acquire(blocking=False):
        return False
    threading.Thread(target=_scan, args=(notify,), daemon=True).start()
    return True


@router.api_route("/cron/scan", methods=["GET", "POST"])
def cron_scan(key: str = ""):
    """Hit every 10 minutes by an external timer (cron-job.org). The calls also keep
    the free Render instance awake."""
    s = get_settings()
    if not s.webhook_secret or not hmac.compare_digest(key, s.webhook_secret):
        return {"ok": False}
    return {"ok": True, "started": start_scan(notify=False)}


def status_text() -> str:
    since = datetime.now(timezone.utc) - timedelta(days=1)
    with session_scope() as db:
        found = db.scalar(select(func.count()).select_from(Job).where(Job.found_at >= since)) or 0
        sent = db.scalar(select(func.count()).select_from(Job)
                         .where(Job.found_at >= since, Job.status.in_(("notified", "saved", "applied")))) or 0
        applied = db.scalar(select(func.count()).select_from(Application).where(Application.applied_at >= since)) or 0
        last = db.scalar(select(func.max(Job.found_at)))
        scan = get_setting(db, "last_scan", None)
        history = get_setting(db, "scan_history", [])
        windows = sorted({p.hours for p in db.scalars(select(SearchProfile).where(SearchProfile.active))})
    running = "\nA scan is running now." if _run_lock.locked() else ""
    last_txt = _ist(last) if last else "never"
    if scan:
        scan_txt = (f"{_ist(datetime.fromisoformat(scan['at']))} by {scan.get('source', '?')}: "
                    f"{scan.get('found', 0)} new, {scan.get('notified', 0)} sent")
    else:
        scan_txt = "not recorded yet"
    window = "/".join(str(h) for h in windows) or "6"
    hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
    recent = [h for h in history if datetime.fromisoformat(h["at"]) >= hour_ago]
    blocked = sum(1 for h in recent if h.get("linkedin_http") not in (None, 200))
    scan_txt += f"\nScans in the last hour: {len(recent)}, blocked by LinkedIn: {blocked}"
    return (f"<b>Last 24 hours</b>\nJobs found: {found}\nSent to you: {sent}\n"
            f"Applied: {applied}\nLast job found: {last_txt}\n\n"
            f"Last scan: {scan_txt}\nSearches LinkedIn posts from the last {window} h; "
            f"only jobs you have not seen are sent.{running}")


def _ist(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(IST).strftime("%d %b %H:%M IST")


@router.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    s = get_settings()
    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if not s.webhook_secret or not hmac.compare_digest(secret, s.webhook_secret):
        return {"ok": False}
    update = await request.json()
    msg = update.get("message") or update.get("edited_message") or {}
    chat_id = str((msg.get("chat") or {}).get("id", ""))
    text = msg.get("text") or ""
    if not text or chat_id != str(s.telegram_chat_id):
        return {"ok": True}  # ignore anyone else

    cmd = _command(text)
    if cmd == "run":
        if start_scan():
            send_message("Searching LinkedIn now. Matches will arrive in a few minutes.")
        else:
            send_message("Could not start a scan right now (one may already be running). "
                         "Any new matches will arrive in a few minutes.")
    elif cmd == "status":
        send_message(status_text())
    else:
        send_message(HELP)
    return {"ok": True}
