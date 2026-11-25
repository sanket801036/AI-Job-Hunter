import os
import tempfile

_db = os.path.join(tempfile.mkdtemp(), "web.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_db}"
os.environ["DASHBOARD_PASSWORD"] = "test-pass"
os.environ["WEBHOOK_SECRET"] = "s"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.config import get_settings  # noqa: E402

get_settings.cache_clear()

from app.db import Base, engine, init_db, session_scope  # noqa: E402
from app.models import Evaluation, Job  # noqa: E402
from app.web.main import app  # noqa: E402


@pytest.fixture()
def client():
    init_db()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with session_scope() as s:
        job = Job(linkedin_id="9", title="AI Engineer", company="Krista", location="Pune",
                  url="https://www.linkedin.com/jobs/view/9/", description="Build RAG agents.",
                  easy_apply=True, status="notified")
        s.add(Evaluation(job=job, is_relevant=True, eligible=True, match_score=81,
                         matched_skills=["RAG"], provider="gemini"))
    return TestClient(app)


def login(c):
    r = c.post("/login", data={"password": "test-pass", "next": "/"}, follow_redirects=False)
    assert r.status_code == 303


def test_pages_need_login(client):
    r = client.get("/jobs", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/login")
    assert client.get("/healthz").status_code == 200


def test_wrong_password_rejected(client):
    r = client.post("/login", data={"password": "nope", "next": "/"}, follow_redirects=False)
    assert "error=1" in r.headers["location"]


def test_jobs_feed_and_detail(client):
    login(client)
    r = client.get("/jobs")
    assert r.status_code == 200 and "AI Engineer" in r.text and "81%" in r.text
    assert client.get("/").status_code == 200
    with session_scope() as s:
        job_id = s.query(Job).one().id
    r = client.get(f"/jobs/{job_id}")
    assert "Build RAG agents." in r.text and "Open on LinkedIn" in r.text
    client.post(f"/jobs/{job_id}/status", data={"status": "saved"})
    assert "AI Engineer" in client.get("/jobs?tab=saved").text


def _docx_bytes(text: str) -> bytes:
    import io

    from docx import Document

    doc = Document()
    doc.add_paragraph(text)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def test_resume_upload_and_profile(client):
    from app.models import Resume, SearchProfile

    login(client)
    r = client.post("/resumes", data={"label": "Full Stack"},
                    files={"file": ("cv.docx", _docx_bytes("Python Django React"), "application/octet-stream")})
    assert r.status_code == 200 and "cv.docx" in r.text
    with session_scope() as s:
        cv = s.query(Resume).one()
        assert "Django" in cv.text
        cv_id = cv.id

    client.post("/profiles", data={"name": "Full Stack", "keywords": "Full Stack Developer",
                                   "hours": "12", "work_types": ["2", "3"], "resume_id": str(cv_id)})
    with session_scope() as s:
        p = s.query(SearchProfile).filter_by(name="Full Stack").one()
        assert p.work_types == "2,3" and p.hours == 12 and p.resume_id == cv_id
        pid = p.id
    client.post(f"/profiles/{pid}/toggle")
    with session_scope() as s:
        assert s.get(SearchProfile, pid).active is False
    assert "Full Stack" in client.get("/profiles").text
    assert client.get(f"/resumes/{cv_id}/download").content[:2] == b"PK"


def test_bad_resume_file_is_rejected(client):
    login(client)
    r = client.post("/resumes", data={"label": "x"}, files={"file": ("cv.txt", b"hello", "text/plain")})
    assert "Upload a PDF or DOCX file" in r.text


def test_application_referral_and_rounds(client):
    from app.models import Application, Referral

    login(client)
    with session_scope() as s:
        job_id = s.query(Job).one().id
    r = client.post("/applications", data={"job_id": str(job_id), "applied_at": "2026-11-25T14:30",
                                           "platform": "Easy Apply", "ctc_told": "10.5 LPA", "notes": "via bot"})
    assert r.status_code == 200 and "Applied 25 Nov 2026, 02:30 PM via Easy Apply" in r.text
    with session_scope() as s:
        a = s.query(Application).one()
        app_id = a.id
        assert a.job.status == "applied"

    client.post(f"/applications/{app_id}/referrals", data={"name": "Dattaraj", "role": "Data Scientist",
                                                           "linkedin_url": "https://linkedin.com/in/x",
                                                           "message": "Hi, could you refer me?"})
    client.post(f"/applications/{app_id}/rounds", data={"name": "Tech 1", "scheduled_at": "2026-11-28T11:00"})
    client.post(f"/applications/{app_id}", data={"stage": "tech_1", "description": "New JD text", "notes": "n"})
    page = client.get(f"/applications/{app_id}").text
    assert "Dattaraj" in page and "Tech 1" in page and "New JD text" in page
    with session_scope() as s:
        ref_id = s.query(Referral).one().id
    client.post(f"/referrals/{ref_id}", data={"status": "referred"})
    with session_scope() as s:
        assert s.get(Referral, ref_id).status == "referred"
    assert "Krista" in client.get("/applications?stage=active").text


def test_manual_application(client):
    login(client)
    r = client.post("/applications", data={"company": "Infor", "title": "Senior Full Stack Engineer",
                                           "link": "https://infor.com/jobs/1", "description": "Python, AWS",
                                           "platform": "Company site"})
    assert r.status_code == 200 and "Infor" in r.text and "Python, AWS" in r.text
    assert "Infor" in client.get("/applications").text


def test_company_notes_block_and_settings(client):
    from app.filters import effective_profile
    from app.models import Company

    login(client)
    r = client.post("/companies/Krista", data={"category": "direct", "notes": "3 rounds, system design",
                                               "website": "https://krista.ai"})
    assert r.status_code == 200 and "3 rounds, system design" in r.text
    assert "Krista" in client.get("/companies").text

    client.post("/settings/block", data={"name": "JunkJobs"})
    client.post("/settings/words", data={"words": "Intern, SAP"})
    assert "JunkJobs" in client.get("/settings").text
    with session_scope() as s:
        prof = effective_profile(s)
        assert "JunkJobs" in prof["skip_companies"] and "SAP" in prof["titles_skip"]
    client.post("/settings/unblock", data={"name": "JunkJobs"})
    with session_scope() as s:
        assert s.query(Company).filter_by(name="JunkJobs").one().blocked is False


def test_i_know_this_and_skills_settings(client):
    from app.filters import effective_profile

    login(client)
    with session_scope() as s:
        job = s.query(Job).one()
        job.evaluation.missing_skills = ["YAML configuration", "Kubernetes"]
        job_id = job.id
    r = client.post(f"/jobs/{job_id}/know", data={"skill": "YAML configuration"})
    assert "Added" in r.text
    with session_scope() as s:
        ev = s.get(Job, job_id).evaluation
        assert ev.missing_skills == ["Kubernetes"] and "YAML configuration" in ev.matched_skills
        assert "YAML configuration" in effective_profile(s)["skills"]

    client.post("/settings/skills", data={"skills": "Audit logging\nRetries, retries", "about_me": "Built HITL agents"})
    with session_scope() as s:
        prof = effective_profile(s)
        assert "Audit logging" in prof["skills"] and prof["about_me"] == "Built HITL agents"
        assert [x.lower() for x in prof["skills"]].count("retries") == 1


def test_fetch_now_page(client):
    from unittest.mock import patch

    from app.linkedin.search import JobCard
    from app.models import SearchProfile

    login(client)
    with session_scope() as s:
        s.add(SearchProfile(name="AI Engineer", keywords="AI Engineer"))
    assert "Under 10 applicants only" in client.get("/fetch").text

    cards = [JobCard("777", "GenAI Engineer", "NewCo", "Pune", "https://l/777", None)]
    with patch("app.pipeline.search", return_value=cards) as search, \
         patch("app.pipeline.time.sleep"), \
         patch("app.pipeline.judge_and_notify_in_background"):
        r = client.post("/fetch", data={"hours": "1", "under_10": "on", "work_types": ["1", "2", "3"]})
    assert search.call_args.kwargs["under_10"] is True
    assert search.call_args.kwargs["hours"] == 1
    assert "1 new job found" in r.text and "GenAI Engineer" in r.text and "checking..." in r.text
