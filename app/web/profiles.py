"""Search profiles (what the bot searches for) and resumes (what it matches against)."""
import io
import re

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Application, Job, Referral, Resume, SearchProfile
from app.web.common import get_db, render

router = APIRouter()

MAX_RESUME_BYTES = 5 * 1024 * 1024
WORK_TYPES = {"1": "On-site", "2": "Remote", "3": "Hybrid"}


def extract_text(filename: str, data: bytes) -> str:
    """Plain text of a PDF or DOCX resume, used in the LLM prompt."""
    name = filename.lower()
    if name.endswith(".pdf"):
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
    elif name.endswith(".docx"):
        from docx import Document

        doc = Document(io.BytesIO(data))
        parts = [p.text for p in doc.paragraphs]
        for table in doc.tables:
            for row in table.rows:
                parts.append(" | ".join(c.text for c in row.cells))
        text = "\n".join(parts)
    else:
        raise ValueError("Upload a PDF or DOCX file")
    return re.sub(r"\n{3,}", "\n\n", text).strip()


# ---------- Search profiles ----------

@router.get("/profiles")
def profiles_page(request: Request, db: Session = Depends(get_db)):
    profiles = db.scalars(select(SearchProfile).order_by(SearchProfile.name)).all()
    counts = dict(db.execute(select(Job.search_profile_id, func.count()).group_by(Job.search_profile_id)).all())
    resumes = db.scalars(select(Resume).order_by(Resume.label)).all()
    return render(request, "profiles.html", active="profiles", profiles=profiles, counts=counts,
                  resumes=resumes, work_types=WORK_TYPES)


def _work_types(values: list[str]) -> str:
    picked = [v for v in values if v in WORK_TYPES]
    return ",".join(picked) or "1,2,3"


@router.post("/profiles")
def save_profile(
    profile_id: str = Form(""),
    name: str = Form(...),
    keywords: str = Form(...),
    hours: int = Form(6),
    work_types: list[str] = Form([]),
    under_10: str = Form(""),
    resume_id: str = Form(""),
    db: Session = Depends(get_db),
):
    name, keywords = name.strip(), keywords.strip()
    if not name or not keywords:
        raise HTTPException(400, "Name and keywords are required")
    hours = max(1, min(hours, 72))
    p = db.get(SearchProfile, int(profile_id)) if profile_id.isdigit() else None
    if p is None:
        if db.scalar(select(SearchProfile).where(SearchProfile.name == name)):
            raise HTTPException(400, "A profile with this name already exists")
        p = SearchProfile(name=name, keywords=keywords)
        db.add(p)
    p.name, p.keywords, p.hours = name, keywords, hours
    p.work_types = _work_types(work_types)
    p.under_10 = under_10 == "on"
    p.resume_id = int(resume_id) if resume_id.isdigit() else None
    db.commit()
    return RedirectResponse("/profiles", status_code=303)


@router.post("/profiles/{profile_id}/toggle")
def toggle_profile(profile_id: int, db: Session = Depends(get_db)):
    p = db.get(SearchProfile, profile_id)
    if p is None:
        raise HTTPException(404, "Profile not found")
    p.active = not p.active
    db.commit()
    return RedirectResponse("/profiles", status_code=303)


@router.post("/profiles/{profile_id}/delete")
def delete_profile(profile_id: int, db: Session = Depends(get_db)):
    p = db.get(SearchProfile, profile_id)
    if p is None:
        raise HTTPException(404, "Profile not found")
    for job in db.scalars(select(Job).where(Job.search_profile_id == profile_id)):
        job.search_profile_id = None  # keep the jobs, just unlink them
    db.delete(p)
    db.commit()
    return RedirectResponse("/profiles", status_code=303)


# ---------- Resumes ----------

@router.get("/resumes")
def resumes_page(request: Request, error: str = "", db: Session = Depends(get_db)):
    resumes = db.scalars(select(Resume).order_by(Resume.uploaded_at.desc())).all()
    used = {r.id: db.scalar(select(func.count()).select_from(Application).where(Application.resume_id == r.id))
            for r in resumes}
    return render(request, "resumes.html", active="resumes", resumes=resumes, used=used, error=error)


@router.post("/resumes")
async def upload_resume(label: str = Form(...), file: UploadFile = File(...), db: Session = Depends(get_db)):
    data = await file.read()
    if not data:
        return RedirectResponse("/resumes?error=The file is empty", status_code=303)
    if len(data) > MAX_RESUME_BYTES:
        return RedirectResponse("/resumes?error=File is larger than 5 MB", status_code=303)
    try:
        text = extract_text(file.filename or "", data)
    except ValueError as e:
        return RedirectResponse(f"/resumes?error={e}", status_code=303)
    except Exception:
        return RedirectResponse("/resumes?error=Could not read this file", status_code=303)
    db.add(Resume(label=label.strip() or file.filename, filename=file.filename, content=data, text=text))
    db.commit()
    return RedirectResponse("/resumes", status_code=303)


@router.get("/resumes/{resume_id}/download")
def download_resume(resume_id: int, db: Session = Depends(get_db)):
    r = db.get(Resume, resume_id)
    if r is None:
        raise HTTPException(404, "Resume not found")
    media = "application/pdf" if r.filename.lower().endswith(".pdf") else \
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", r.filename)
    return Response(r.content, media_type=media, headers={"Content-Disposition": f'inline; filename="{safe}"'})


@router.post("/resumes/{resume_id}/delete")
def delete_resume(resume_id: int, db: Session = Depends(get_db)):
    r = db.get(Resume, resume_id)
    if r is None:
        raise HTTPException(404, "Resume not found")
    in_use = db.scalar(select(func.count()).select_from(Application).where(Application.resume_id == resume_id)) \
        or db.scalar(select(func.count()).select_from(Referral).where(Referral.resume_id == resume_id))
    if in_use:
        return RedirectResponse("/resumes?error=This resume is linked to applications, so it is kept", status_code=303)
    for p in db.scalars(select(SearchProfile).where(SearchProfile.resume_id == resume_id)):
        p.resume_id = None
    db.delete(r)
    db.commit()
    return RedirectResponse("/resumes", status_code=303)
