"""Send a job to my Telegram chat: the key facts, a short JD preview and links."""
import html
import logging

import httpx

from app.config import get_settings

log = logging.getLogger(__name__)

API = "https://api.telegram.org/bot{token}/{method}"
JD_PREVIEW_CHARS = 900


def _e(text) -> str:
    return html.escape(str(text or ""), quote=False)


def format_job(job, verdict) -> str:
    """HTML message for one job. `job` and `verdict` can be ORM rows or any object with
    the same attributes."""
    years = ""
    if verdict.min_years is not None:
        years = f"{verdict.min_years}-{verdict.max_years} yrs" if verdict.max_years else f"{verdict.min_years}+ yrs"
    facts = " | ".join(x for x in [f"Match {verdict.match_score}%", years, job.applicants, getattr(job, "posted_ago", "")] if x)

    if job.easy_apply:
        how = "Easy Apply on LinkedIn"
    elif job.apply_url:
        how = f'Company site: <a href="{_e(job.apply_url)}">apply link</a>'
    elif job.easy_apply is False:
        how = "Company site (open the LinkedIn job to reach it)"
    else:
        how = "See the LinkedIn job"

    jd = (job.description or "").strip()
    if len(jd) > JD_PREVIEW_CHARS:
        jd = jd[:JD_PREVIEW_CHARS].rsplit(" ", 1)[0] + " ..."

    lines = [
        f"🟢 <b>{_e(job.title)}</b>",
        f"🏢 {_e(job.company)}  ·  📍 {_e(job.location)}",
        f"📊 {_e(facts)}",
    ]
    if verdict.matched_skills:
        lines.append("✅ " + _e(", ".join(verdict.matched_skills[:8])))
    if verdict.missing_skills:
        lines.append("❌ " + _e(", ".join(verdict.missing_skills[:6])))
    if verdict.red_flags:
        lines.append("⚠️ " + _e(", ".join(verdict.red_flags[:4])))
    if verdict.reason:
        lines.append(f"<i>{_e(verdict.reason)}</i>")
    lines += [
        "",
        f"📝 <b>How to apply:</b> {how}",
        f'🔗 <a href="{_e(job.url)}">Open on LinkedIn</a>',
        "",
        f"<b>JD preview</b>\n<blockquote expandable>{_e(jd)}</blockquote>",
    ]
    return "\n".join(lines)


def buttons(job) -> dict:
    row = [{"text": "Open on LinkedIn", "url": job.url}]
    if job.apply_url:
        row.append({"text": "Apply on company site", "url": job.apply_url})
    return {"inline_keyboard": [row]}


def send_message(text: str, reply_markup: dict | None = None) -> bool:
    s = get_settings()
    if not (s.telegram_bot_token and s.telegram_chat_id):
        log.warning("Telegram not configured, message not sent")
        return False
    body = {
        "chat_id": s.telegram_chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if reply_markup:
        body["reply_markup"] = reply_markup
    try:
        r = httpx.post(API.format(token=s.telegram_bot_token, method="sendMessage"), json=body, timeout=20)
        if r.status_code != 200:
            log.warning("Telegram returned HTTP %d: %s", r.status_code, r.text[:200])
            return False
        return True
    except httpx.HTTPError as e:
        log.warning("Telegram send failed: %s", e)
        return False


def send_job(job, verdict) -> bool:
    return send_message(format_job(job, verdict), buttons(job))
