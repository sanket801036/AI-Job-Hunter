"""Telegram webhook: lets me start a scan or ask for a status from the chat.

Telegram calls POST /telegram/webhook for every message sent to the bot. Only my
chat id is answered, and the request must carry the secret set in setWebhook.
"""
import hmac
import logging
import threading
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Request
from sqlalchemy import func, select

from app.config import get_settings
from app.db import session_scope
from app.models import Application, Job
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


def _scan() -> None:
    from app.pipeline import run_once

    try:
        stats = run_once()
        send_message(
            f"Scan finished: {stats['found']} new jobs, {stats['judged']} checked, "
            f"{stats['notified']} sent to you."
            + (f" {stats['errors']} errors." if stats.get("errors") else "")
        )
    except Exception:
        log.exception("scan from Telegram failed")
        send_message("Scan failed. Check the server logs.")
    finally:
        _run_lock.release()


def start_scan() -> bool:
    """Start a scan in a background thread. False if one is already running."""
    if not _run_lock.acquire(blocking=False):
        return False
    threading.Thread(target=_scan, daemon=True).start()
    return True


def status_text() -> str:
    since = datetime.now(timezone.utc) - timedelta(days=1)
    with session_scope() as db:
        found = db.scalar(select(func.count()).select_from(Job).where(Job.found_at >= since)) or 0
        sent = db.scalar(select(func.count()).select_from(Job)
                         .where(Job.found_at >= since, Job.status.in_(("notified", "saved", "applied")))) or 0
        applied = db.scalar(select(func.count()).select_from(Application).where(Application.applied_at >= since)) or 0
        last = db.scalar(select(func.max(Job.found_at)))
    running = "\nA scan is running now." if _run_lock.locked() else ""
    last_txt = last.strftime("%d %b %H:%M UTC") if last else "never"
    return (f"<b>Last 24 hours</b>\nJobs found: {found}\nSent to you: {sent}\n"
            f"Applied: {applied}\nLast job found: {last_txt}{running}")


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
            send_message("A scan is already running. Please wait for it to finish.")
    elif cmd == "status":
        send_message(status_text())
    else:
        send_message(HELP)
    return {"ok": True}
