"""Dashboard: jobs the bot found, my applications, referrals, companies, settings."""
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from fastapi import BackgroundTasks, Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db import init_db
from app.models import Application, Evaluation, Job, SearchProfile
from app.web import auth, companies, profiles, telegram_bot, tracker
from app.web.common import get_db, render, templates

@asynccontextmanager
async def lifespan(_app):
    init_db()
    yield


app = FastAPI(title="AI Job Hunter", docs_url=None, redoc_url=None, lifespan=lifespan)
app.include_router(profiles.router)
app.include_router(tracker.router)
app.include_router(companies.router)
app.include_router(telegram_bot.router)

PUBLIC_PATHS = {"/login", "/healthz", "/favicon.ico", "/telegram/webhook"}


@app.middleware("http")
async def require_login(request: Request, call_next):
    if request.url.path not in PUBLIC_PATHS and not request.url.path.startswith("/static") \
            and not auth.is_logged_in(request):
        return RedirectResponse(f"/login?next={request.url.path}", status_code=303)
    return await call_next(request)


# ---------- Login ----------

@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/favicon.ico")
def favicon():
    return Response(status_code=204)


@app.get("/login")
def login_page(request: Request, next: str = "/", error: str = ""):
    from app.config import get_settings
    return templates.TemplateResponse(request, "login.html", {
        "next": next, "error": error, "configured": bool(get_settings().dashboard_password)})


@app.post("/login")
def login(password: str = Form(...), next: str = Form("/")):
    if not auth.password_ok(password):
        return RedirectResponse(f"/login?error=1&next={next}", status_code=303)
    target = next if next.startswith("/") and not next.startswith("//") else "/"
    resp = RedirectResponse(target, status_code=303)
    resp.set_cookie(auth.COOKIE, auth.make_token(), max_age=auth.MAX_AGE, httponly=True, samesite="lax")
    return resp


@app.post("/logout")
def logout():
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie(auth.COOKIE)
    return resp


# ---------- Overview ----------

@app.get("/")
def overview(request: Request, db: Session = Depends(get_db)):
    counts = dict(db.execute(select(Job.status, func.count()).group_by(Job.status)).all())
    since = datetime.now(timezone.utc) - timedelta(days=1)
    stats = {
        "found_today": db.scalar(select(func.count()).select_from(Job).where(Job.found_at >= since)) or 0,
        "notified": counts.get("notified", 0),
        "applied": db.scalar(select(func.count()).select_from(Application)) or 0,
        "interviews": db.scalar(select(func.count()).select_from(Application).where(
            Application.stage.notin_(["applied", "rejected", "ghosted"]))) or 0,
    }
    latest = db.scalars(select(Job).where(Job.status.in_(["notified", "eligible", "saved"]))
                        .order_by(Job.found_at.desc()).limit(8)).all()
    last_run = db.scalar(select(func.max(Job.found_at)))
    return render(request, "overview.html", active="overview", stats=stats, latest=latest, last_run=last_run)


# ---------- Jobs ----------

JOB_TABS = {
    "matches": ["notified", "eligible"],
    "saved": ["saved"],
    "applied": ["applied"],
    "skipped": ["skipped"],
    "not_eligible": ["not_eligible", "filtered"],
    "all": None,
}


@app.get("/jobs")
def jobs(request: Request, tab: str = "matches", q: str = "", easy: str = "", profile: str = "",
         min_score: int = 0, db: Session = Depends(get_db)):
    stmt = select(Job).outerjoin(Evaluation).order_by(Job.found_at.desc())
    statuses = JOB_TABS.get(tab, JOB_TABS["matches"])
    if statuses:
        stmt = stmt.where(Job.status.in_(statuses))
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Job.title.ilike(like), Job.company.ilike(like), Job.location.ilike(like)))
    if easy == "1":
        stmt = stmt.where(Job.easy_apply.is_(True))
    elif easy == "0":
        stmt = stmt.where(Job.easy_apply.is_(False))
    if profile.isdigit():
        stmt = stmt.where(Job.search_profile_id == int(profile))
    if min_score:
        stmt = stmt.where(Evaluation.match_score >= min_score)
    rows = db.scalars(stmt.limit(200)).all()
    tab_counts = {
        t: db.scalar(select(func.count()).select_from(Job).where(Job.status.in_(s))) if s
        else db.scalar(select(func.count()).select_from(Job))
        for t, s in JOB_TABS.items()
    }
    profiles = db.scalars(select(SearchProfile).order_by(SearchProfile.name)).all()
    return render(request, "jobs.html", active="jobs", jobs=rows, tab=tab, q=q, easy=easy,
                  profile=profile, min_score=min_score, tab_counts=tab_counts, profiles=profiles)


@app.get("/jobs/{job_id}")
def job_detail(job_id: int, request: Request, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    return render(request, "job_detail.html", active="jobs", job=job, ev=job.evaluation)


@app.post("/jobs/{job_id}/status")
def set_job_status(job_id: int, status: str = Form(...), back: str = Form(""), db: Session = Depends(get_db)):
    if status not in {"saved", "skipped", "notified"}:
        raise HTTPException(400, "Unknown status")
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    job.status = status
    db.commit()
    return RedirectResponse(back or f"/jobs/{job_id}", status_code=303)


@app.post("/jobs/{job_id}/know")
def i_know_this(job_id: int, skill: str = Form(...), db: Session = Depends(get_db)):
    """The LLM listed a skill as missing but I have it: remember it for every future check."""
    from app.filters import add_skill

    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    add_skill(db, skill)
    if job.evaluation and skill in (job.evaluation.missing_skills or []):
        job.evaluation.missing_skills = [s for s in job.evaluation.missing_skills if s != skill]
        job.evaluation.matched_skills = [*(job.evaluation.matched_skills or []), skill]
    db.commit()
    return RedirectResponse(f"/jobs/{job_id}?added={quote(skill)}", status_code=303)


@app.post("/jobs/{job_id}/recheck")
def recheck(job_id: int, db: Session = Depends(get_db)):
    """Ask the LLM again with my current skills."""
    from app.llm.client import AllProvidersFailed
    from app.pipeline import recheck_job

    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    try:
        recheck_job(db, job)
        db.commit()
        return RedirectResponse(f"/jobs/{job_id}?rechecked=1", status_code=303)
    except AllProvidersFailed:
        db.rollback()
        return RedirectResponse(f"/jobs/{job_id}?recheck_failed=1", status_code=303)



# ---------- Fetch now ----------

HOUR_CHOICES = [(1, "Last 1 hour"), (3, "Last 3 hours"), (6, "Last 6 hours"), (12, "Last 12 hours"), (24, "Last 24 hours")]
WORK_TYPES = {"1": "On-site", "2": "Remote", "3": "Hybrid"}


@app.get("/fetch")
def fetch_page(request: Request, since: str = "", added: int = -1, db: Session = Depends(get_db)):
    profiles = db.scalars(select(SearchProfile).order_by(SearchProfile.name)).all()
    results, hidden, pending = [], 0, 0
    if since:
        try:
            since_dt = datetime.fromisoformat(since)
        except ValueError:
            since_dt = None
        if since_dt:
            batch = db.scalars(select(Job).where(Job.found_at >= since_dt).order_by(Job.found_at.desc())).all()
            for j in batch:
                if j.status in ("filtered", "not_eligible"):
                    hidden += 1
                else:
                    results.append(j)
                    pending += j.status == "new"
    # best matches first, jobs still being checked at the end
    results.sort(key=lambda j: (j.status == "new", -(j.evaluation.match_score if j.evaluation else 0)))
    return render(request, "fetch.html", active="fetch", profiles=profiles, hour_choices=HOUR_CHOICES,
                  work_types=WORK_TYPES, since=since, added=added, results=results, hidden=hidden,
                  pending=pending)


@app.post("/fetch")
def fetch_run(background: BackgroundTasks, profile_ids: list[int] = Form([]), hours: int = Form(1),
              under_10: str = Form(""), work_types: list[str] = Form([]), db: Session = Depends(get_db)):
    from app.pipeline import fetch_now, judge_and_notify_in_background

    if not profile_ids:
        profile_ids = list(db.scalars(select(SearchProfile.id).where(SearchProfile.active.is_(True))))
    wt = ",".join(w for w in work_types if w in WORK_TYPES) or "1,2,3"
    started = datetime.now(timezone.utc)
    added = fetch_now(profile_ids, max(1, min(hours, 72)), under_10 == "on", wt)
    background.add_task(judge_and_notify_in_background)
    return RedirectResponse(f"/fetch?since={quote(started.isoformat())}&added={added}", status_code=303)
