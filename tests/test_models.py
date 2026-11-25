import os
import tempfile

_db = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_db}"

from app.db import init_db, session_scope  # noqa: E402
from app.models import Application, Contact, Job, Referral, Resume, SearchProfile  # noqa: E402


def test_tables_and_relations():
    init_db()
    with session_scope() as s:
        cv = Resume(label="AI Engineer", filename="cv.pdf", content=b"%PDF", text="Python, RAG")
        profile = SearchProfile(name="AI Engineer", keywords="AI Engineer, LLM Engineer", resume=cv)
        job = Job(linkedin_id="123", title="AI Engineer", url="https://x", search_profile=profile)
        app = Application(job=job, resume=cv, platform="Easy Apply")
        s.add(Referral(contact=Contact(name="A", company="Krista"), application=app, resume=cv))

    with session_scope() as s:
        job = s.query(Job).one()
        assert job.search_profile.keyword_list == ["AI Engineer", "LLM Engineer"]
        assert job.application.referrals[0].contact.company == "Krista"
        assert job.application.resume.label == "AI Engineer"
