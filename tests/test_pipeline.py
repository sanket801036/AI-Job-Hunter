import os
import tempfile

_db = os.path.join(tempfile.mkdtemp(), "pipe.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_db}"

from unittest.mock import patch  # noqa: E402

from app import pipeline  # noqa: E402
from app.judge import Verdict  # noqa: E402
from app.linkedin.detail import JobDetail  # noqa: E402
from app.linkedin.search import JobCard  # noqa: E402

PROFILE = {"experience_years": 3, "max_years_ok": 5, "skills": [], "locations_ok": [],
           "titles_skip": ["Principal"], "skip_companies": []}

CARDS = [
    JobCard("1", "AI Engineer", "Good Co", "Pune", "https://l/1", None),
    JobCard("2", "Principal AI Engineer", "Big Co", "Pune", "https://l/2", None),
    JobCard("3", "ML Engineer", "Other Co", "Pune", "https://l/3", None),
]


def fake_judge(title, *a, **kw):
    ok = title == "AI Engineer"
    return Verdict(is_relevant=True, eligible=ok, match_score=80 if ok else 30), "gemini"


def test_run_once_end_to_end():
    # other test modules may share the same engine; start from empty tables
    from app.db import Base, engine, init_db
    init_db()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)

    with patch.object(pipeline, "search", return_value=CARDS), \
         patch.object(pipeline, "fetch_detail", return_value=JobDetail(description="JD", easy_apply=True)), \
         patch.object(pipeline, "judge", side_effect=fake_judge), \
         patch.object(pipeline, "send_job", return_value=True) as sent, \
         patch("app.filters.get_profile", return_value=PROFILE), \
         patch.object(pipeline.time, "sleep"):
        stats = pipeline.run_once()
        assert stats["found"] == 3
        assert stats["filtered"] == 1  # Principal
        assert stats["notified"] == 1  # only the eligible one
        assert sent.call_count == 1

        # second run: nothing new, nothing sent again
        stats = pipeline.run_once()
        assert stats["found"] == 0 and stats["notified"] == 0
