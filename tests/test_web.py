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
