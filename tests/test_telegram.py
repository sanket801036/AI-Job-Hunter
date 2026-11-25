from types import SimpleNamespace

from app.judge import Verdict
from app.notify.telegram import buttons, format_job


def _job(**kw):
    base = dict(title="AI Engineer <Remote>", company="Krista & Co", location="Pune",
                url="https://www.linkedin.com/jobs/view/1/", applicants="12 applicants",
                posted_ago="1 hour ago", easy_apply=True, apply_url="", description="Build agents. " * 200)
    base.update(kw)
    return SimpleNamespace(**base)


VERDICT = Verdict(is_relevant=True, min_years=3, max_years=5, eligible=True, match_score=82,
                  matched_skills=["RAG", "LangGraph"], missing_skills=["Kubernetes"], reason="Good fit")


def test_message_has_facts_links_and_escaped_text():
    msg = format_job(_job(), VERDICT)
    assert "AI Engineer &lt;Remote&gt;" in msg and "Krista &amp; Co" in msg
    assert "Match 82%" in msg and "3-5 yrs" in msg and "12 applicants" in msg
    assert "Easy Apply on LinkedIn" in msg
    assert 'href="https://www.linkedin.com/jobs/view/1/"' in msg
    assert len(msg) < 4096  # Telegram limit


def test_company_site_job_gets_apply_button():
    job = _job(easy_apply=False, apply_url="https://careers.example.com/42")
    assert "Company site" in format_job(job, VERDICT)
    assert [b["text"] for b in buttons(job)["inline_keyboard"][0]] == ["Open on LinkedIn", "Apply on company site"]
