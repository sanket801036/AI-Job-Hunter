"""Companies: one page per company with my notes, jobs, applications and people;
plus the settings page (skip lists and connection checks)."""
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_profile, get_settings
from app.filters import EXTRA_TITLE_WORDS, get_setting, set_setting
from app.models import Application, Company, Contact, Job
from app.web.common import get_db, render

router = APIRouter()

CATEGORIES = [
    ("", "Not set"),
    ("direct", "Direct employer"),
    ("staffing", "Staffing / consulting (hires for clients)"),
    ("marketplace", "Freelance / talent marketplace"),
    ("aggregator", "Job board / aggregator"),
]


def _company(db: Session, name: str, create: bool = False) -> Company | None:
    c = db.scalar(select(Company).where(func.lower(Company.name) == name.lower()))
    if c is None and create:
        c = Company(name=name)
        db.add(c)
    return c


@router.get("/companies")
def companies(request: Request, q: str = "", db: Session = Depends(get_db)):
    job_counts = dict(db.execute(select(Job.company, func.count()).where(Job.company != "")
                                 .group_by(Job.company)).all())
    app_counts = dict(db.execute(select(Job.company, func.count()).join(Application).group_by(Job.company)).all())
    saved = {c.name: c for c in db.scalars(select(Company))}
    names = sorted({*job_counts, *saved}, key=str.lower)
    if q:
        names = [n for n in names if q.lower() in n.lower()]
    # companies I applied to first, then the rest
    names.sort(key=lambda n: (-app_counts.get(n, 0), n.lower()))
    return render(request, "companies.html", active="companies", names=names, saved=saved,
                  job_counts=job_counts, app_counts=app_counts, q=q, categories=dict(CATEGORIES))


@router.get("/companies/{name}")
def company_detail(name: str, request: Request, db: Session = Depends(get_db)):
    c = _company(db, name)
    jobs = db.scalars(select(Job).where(func.lower(Job.company) == name.lower()).order_by(Job.found_at.desc())).all()
    contacts = db.scalars(select(Contact).where(func.lower(Contact.company) == name.lower())).all()
    if c is None and not jobs and not contacts:
        raise HTTPException(404, "Company not found")
    apps = [j.application for j in jobs if j.application]
    return render(request, "company_detail.html", active="companies", name=c.name if c else name, c=c,
                  jobs=jobs, apps=apps, contacts=contacts, categories=CATEGORIES)


@router.post("/companies/{name}")
def save_company(name: str, category: str = Form(""), website: str = Form(""), notes: str = Form(""),
                 blocked: str = Form(""), db: Session = Depends(get_db)):
    c = _company(db, name, create=True)
    c.category = category if category in dict(CATEGORIES) else ""
    c.website, c.notes, c.blocked = website.strip(), notes.strip(), blocked == "on"
    db.commit()
    return RedirectResponse(f"/companies/{c.name}?saved=1", status_code=303)


@router.post("/contacts/{contact_id}")
def save_contact(contact_id: int, role: str = Form(""), linkedin_url: str = Form(""), notes: str = Form(""),
                 db: Session = Depends(get_db)):
    ct = db.get(Contact, contact_id)
    if ct is None:
        raise HTTPException(404, "Contact not found")
    ct.role, ct.linkedin_url, ct.notes = role.strip(), linkedin_url.strip(), notes.strip()
    db.commit()
    return RedirectResponse(f"/companies/{ct.company}#people", status_code=303)


# ---------- Settings ----------

@router.get("/settings")
def settings_page(request: Request, msg: str = "", db: Session = Depends(get_db)):
    s = get_settings()
    blocked = db.scalars(select(Company).where(Company.blocked.is_(True)).order_by(Company.name)).all()
    return render(request, "settings.html", active="settings", msg=msg, blocked=blocked,
                  yaml_companies=get_profile().get("skip_companies", []),
                  yaml_words=get_profile().get("titles_skip", []),
                  extra_words=get_setting(db, EXTRA_TITLE_WORDS, []),
                  telegram_ok=bool(s.telegram_bot_token and s.telegram_chat_id),
                  providers=[(p, bool(getattr(s, _key_attr(p), ""))) for p in s.providers])


def _key_attr(provider: str) -> str:
    return {"gemini2": "gemini_api_key_2"}.get(provider, f"{provider}_api_key")


@router.post("/settings/block")
def block_company(name: str = Form(...), db: Session = Depends(get_db)):
    if name.strip():
        c = _company(db, name.strip(), create=True)
        c.blocked = True
        db.commit()
    return RedirectResponse("/settings", status_code=303)


@router.post("/settings/unblock")
def unblock_company(name: str = Form(...), db: Session = Depends(get_db)):
    c = _company(db, name)
    if c:
        c.blocked = False
        db.commit()
    return RedirectResponse("/settings", status_code=303)


@router.post("/settings/words")
def save_words(words: str = Form(""), db: Session = Depends(get_db)):
    cleaned = sorted({w.strip() for w in words.split(",") if w.strip()}, key=str.lower)
    set_setting(db, EXTRA_TITLE_WORDS, cleaned)
    db.commit()
    return RedirectResponse("/settings", status_code=303)


@router.post("/settings/test-telegram")
def test_telegram():
    from app.notify.telegram import send_message

    ok = send_message("Test from the AI Job Hunter dashboard. Notifications are working.")
    return RedirectResponse(f"/settings?msg={'Telegram test sent' if ok else 'Telegram test failed'}", status_code=303)


@router.post("/settings/test-llm")
def test_llm():
    from app.llm.client import complete_json

    try:
        _, provider = complete_json("Reply with JSON only.", 'Return {"ok": true}')
        msg = f"LLM answered via {provider}"
    except Exception as e:
        msg = f"LLM test failed: {str(e)[:150]}"
    return RedirectResponse(f"/settings?msg={msg}", status_code=303)
