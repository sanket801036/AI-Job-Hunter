"""Everything after I apply: the application itself, referral asks and interview rounds."""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import Application, Contact, InterviewRound, Job, Referral, Resume
from app.web.common import get_db, parse_local_datetime, render

router = APIRouter()

STAGES = [
    ("applied", "Applied"),
    ("hr_screen", "HR screen"),
    ("assessment", "Assessment"),
    ("tech_1", "Tech round 1"),
    ("tech_2", "Tech round 2"),
    ("manager", "Manager / HR round"),
    ("offer", "Offer"),
    ("rejected", "Rejected"),
    ("ghosted", "No response"),
]
STAGE_LABELS = dict(STAGES)
CLOSED_STAGES = {"applied", "rejected", "ghosted"}  # not "in interviews"
PLATFORMS = ["Easy Apply", "Company site", "Referral", "Naukri", "Email", "Other"]
REFERRAL_STATUSES = [
    ("connection_sent", "Connection sent"),
    ("connected", "Connected"),
    ("asked", "Referral asked"),
    ("referred", "Referred"),
    ("declined", "Declined"),
    ("no_reply", "No reply"),
]
ROUND_RESULTS = ["pending", "passed", "failed"]

CTX = {"stages": STAGES, "stage_labels": STAGE_LABELS, "platforms": PLATFORMS,
       "referral_statuses": REFERRAL_STATUSES, "round_results": ROUND_RESULTS}


def _get_app(db: Session, app_id: int) -> Application:
    a = db.get(Application, app_id)
    if a is None:
        raise HTTPException(404, "Application not found")
    return a


def _resume_id(value: str) -> int | None:
    return int(value) if value.isdigit() else None


# ---------- Applications ----------

@router.get("/applications")
def applications(request: Request, stage: str = "", q: str = "", db: Session = Depends(get_db)):
    stmt = select(Application).join(Job).order_by(Application.applied_at.desc())
    if stage == "active":
        stmt = stmt.where(Application.stage.notin_(CLOSED_STAGES))
    elif stage in STAGE_LABELS:
        stmt = stmt.where(Application.stage == stage)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Job.company.ilike(like), Job.title.ilike(like)))
    rows = db.scalars(stmt).all()
    stage_counts = dict(db.execute(select(Application.stage, func.count()).group_by(Application.stage)).all())
    return render(request, "applications.html", active="applications", apps=rows, stage=stage, q=q,
                  stage_counts=stage_counts, **CTX)


@router.get("/applications/new")
def new_application(request: Request, job_id: int | None = None, db: Session = Depends(get_db)):
    job = db.get(Job, job_id) if job_id else None
    if job and job.application:
        return RedirectResponse(f"/applications/{job.application.id}", status_code=303)
    resumes = db.scalars(select(Resume).order_by(Resume.label)).all()
    default_resume = job.search_profile.resume_id if job and job.search_profile else None
    platform = "Easy Apply" if job and job.easy_apply else ("Company site" if job else "")
    return render(request, "application_new.html", active="applications", job=job, resumes=resumes,
                  default_resume=default_resume, platform=platform,
                  now=datetime.now(timezone.utc), **CTX)


@router.post("/applications")
def create_application(
    job_id: str = Form(""),
    company: str = Form(""),
    title: str = Form(""),
    location: str = Form(""),
    link: str = Form(""),
    description: str = Form(""),
    applied_at: str = Form(""),
    resume_id: str = Form(""),
    platform: str = Form(""),
    ctc_told: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    job = db.get(Job, int(job_id)) if job_id.isdigit() else None
    if job is None:
        if not company.strip() or not title.strip():
            raise HTTPException(400, "Company and role are required")
        # applied outside the bot (Naukri, referral, career page): keep it in the same history
        job = Job(linkedin_id=f"manual-{uuid.uuid4().hex[:10]}", title=title.strip(), company=company.strip(),
                  location=location.strip(), url=link.strip(), description=description.strip())
        db.add(job)
    elif job.application:
        return RedirectResponse(f"/applications/{job.application.id}", status_code=303)
    elif description.strip():
        job.description = description.strip()
    job.status = "applied"
    a = Application(job=job, resume_id=_resume_id(resume_id), platform=platform, ctc_told=ctc_told.strip(),
                    notes=notes.strip(), applied_at=parse_local_datetime(applied_at) or datetime.now(timezone.utc))
    db.add(a)
    db.commit()
    return RedirectResponse(f"/applications/{a.id}", status_code=303)


@router.get("/applications/{app_id}")
def application_detail(app_id: int, request: Request, db: Session = Depends(get_db)):
    a = _get_app(db, app_id)
    resumes = db.scalars(select(Resume).order_by(Resume.label)).all()
    known_contacts = db.scalars(select(Contact).where(Contact.company == a.job.company).order_by(Contact.name)).all()
    return render(request, "application_detail.html", active="applications", a=a, job=a.job,
                  resumes=resumes, known_contacts=known_contacts, **CTX)


@router.post("/applications/{app_id}")
def update_application(
    app_id: int,
    stage: str = Form(...),
    applied_at: str = Form(""),
    resume_id: str = Form(""),
    platform: str = Form(""),
    ctc_told: str = Form(""),
    notes: str = Form(""),
    description: str = Form(""),
    link: str = Form(""),
    db: Session = Depends(get_db),
):
    a = _get_app(db, app_id)
    if stage not in STAGE_LABELS:
        raise HTTPException(400, "Unknown stage")
    a.stage = stage
    a.applied_at = parse_local_datetime(applied_at) or a.applied_at
    a.resume_id = _resume_id(resume_id)
    a.platform, a.ctc_told, a.notes = platform, ctc_told.strip(), notes.strip()
    a.job.description = description.strip()
    if link.strip():
        a.job.url = link.strip()
    db.commit()
    return RedirectResponse(f"/applications/{app_id}?saved=1", status_code=303)


@router.post("/applications/{app_id}/delete")
def delete_application(app_id: int, db: Session = Depends(get_db)):
    a = _get_app(db, app_id)
    for r in a.referrals:
        r.application_id = None  # keep the person and the ask, only unlink
    for rnd in a.rounds:
        db.delete(rnd)
    job = a.job
    db.delete(a)
    if job.linkedin_id.startswith("manual-"):
        db.delete(job)
    else:
        job.status = "notified"
    db.commit()
    return RedirectResponse("/applications", status_code=303)


# ---------- Referrals ----------

@router.post("/applications/{app_id}/referrals")
def add_referral(
    app_id: int,
    contact_id: str = Form(""),
    name: str = Form(""),
    role: str = Form(""),
    linkedin_url: str = Form(""),
    message: str = Form(""),
    resume_id: str = Form(""),
    status: str = Form("connection_sent"),
    db: Session = Depends(get_db),
):
    a = _get_app(db, app_id)
    contact = db.get(Contact, int(contact_id)) if contact_id.isdigit() else None
    if contact is None:
        if not name.strip():
            raise HTTPException(400, "Name is required")
        contact = Contact(name=name.strip(), company=a.job.company, role=role.strip(), linkedin_url=linkedin_url.strip())
        db.add(contact)
    db.add(Referral(contact=contact, application=a, message=message.strip(),
                    resume_id=_resume_id(resume_id) or a.resume_id,
                    status=status if status in dict(REFERRAL_STATUSES) else "connection_sent"))
    db.commit()
    return RedirectResponse(f"/applications/{app_id}#referrals", status_code=303)


@router.post("/referrals/{ref_id}")
def update_referral(ref_id: int, status: str = Form(...), db: Session = Depends(get_db)):
    r = db.get(Referral, ref_id)
    if r is None:
        raise HTTPException(404, "Referral not found")
    if status not in dict(REFERRAL_STATUSES):
        raise HTTPException(400, "Unknown status")
    r.status = status
    db.commit()
    back = f"/applications/{r.application_id}#referrals" if r.application_id else f"/companies/{r.contact.company}"
    return RedirectResponse(back, status_code=303)


# ---------- Interview rounds ----------

@router.post("/applications/{app_id}/rounds")
def add_round(app_id: int, name: str = Form(...), scheduled_at: str = Form(""), notes: str = Form(""),
              db: Session = Depends(get_db)):
    a = _get_app(db, app_id)
    db.add(InterviewRound(application=a, name=name.strip(), scheduled_at=parse_local_datetime(scheduled_at),
                          notes=notes.strip()))
    db.commit()
    return RedirectResponse(f"/applications/{app_id}#rounds", status_code=303)


@router.post("/rounds/{round_id}")
def update_round(round_id: int, result: str = Form(...), notes: str = Form(""), db: Session = Depends(get_db)):
    rnd = db.get(InterviewRound, round_id)
    if rnd is None:
        raise HTTPException(404, "Round not found")
    if result not in ROUND_RESULTS:
        raise HTTPException(400, "Unknown result")
    rnd.result, rnd.notes = result, notes.strip()
    db.commit()
    return RedirectResponse(f"/applications/{rnd.application_id}#rounds", status_code=303)
