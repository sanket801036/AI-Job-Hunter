"""One full run: search -> details -> eligibility -> Telegram. GitHub Actions calls this
every 10 minutes; it can also be run by hand with `python -m app.pipeline`.

Job statuses written here:
  new          found, not judged yet (LLM was down) - retried next run
  filtered     skipped by a fixed rule before any LLM call
  not_eligible judged, not a fit
  eligible     judged a fit but not sent (Telegram down or per-run limit hit)
  notified     sent to Telegram
"""
import logging
import random
import time

import httpx
from sqlalchemy import select

from app.config import get_settings
from app.db import init_db, session_scope
from app.filters import effective_profile
from app.judge import judge, pre_filter
from app.linkedin.detail import fetch_detail
from app.linkedin.search import HEADERS, dedupe, search
from app.llm.client import AllProvidersFailed
from app.models import Evaluation, Job, SearchProfile
from app.notify.telegram import send_job

log = logging.getLogger("pipeline")

MAX_NEW_JOBS_PER_RUN = 30  # keeps one run well inside the 10 minute window
MAX_NOTIFICATIONS_PER_RUN = 10


def ensure_default_profile(session) -> None:
    """First run: create a search profile from the .env settings so there is something to search."""
    if session.scalar(select(SearchProfile.id).limit(1)) is None:
        s = get_settings()
        session.add(SearchProfile(name="AI Engineer", keywords=s.search_keywords, hours=s.search_hours,
                                  work_types=s.search_work_types, geo_id=s.search_geo_id))
        session.flush()


def collect_new_jobs(session, client: httpx.Client) -> int:
    """Search every active profile and store jobs we have not seen before."""
    pages = get_settings().search_pages
    seen = set(session.scalars(select(Job.linkedin_id)))
    added = 0
    for profile in session.scalars(select(SearchProfile).where(SearchProfile.active.is_(True))):
        for keyword in profile.keyword_list:
            cards = search(keyword, hours=profile.hours, work_types=profile.work_types,
                           geo_id=profile.geo_id, pages=pages, client=client)
            for card in dedupe(cards, seen):
                seen.add(card.linkedin_id)
                session.add(Job(linkedin_id=card.linkedin_id, title=card.title, company=card.company,
                                location=card.location, url=card.url, posted_at=card.posted_at,
                                search_profile_id=profile.id))
                added += 1
            time.sleep(random.uniform(2, 4))
    session.flush()
    return added


def process_job(session, job: Job, client: httpx.Client, profile: dict) -> str:
    reason = pre_filter(job.title, job.company, profile)
    if reason:
        session.add(Evaluation(job=job, reason=reason, provider="rule"))
        job.status = "filtered"
        return job.status

    if not job.description:
        detail = fetch_detail(job.linkedin_id, client=client)
        if detail is None:
            return job.status  # stays "new", retried next run
        job.description = detail.description
        job.seniority = detail.seniority
        job.employment_type = detail.employment_type
        job.applicants = detail.applicants
        job.easy_apply = detail.easy_apply
        job.apply_url = detail.apply_url
        time.sleep(random.uniform(2, 5))

    sp = job.search_profile
    verdict, provider = judge(
        job.title, job.company, job.location, job.description,
        looking_for=sp.name if sp else "AI Engineer",
        resume_text=sp.resume.text if sp and sp.resume else "",
        profile=profile,
    )
    session.add(Evaluation(job=job, provider=provider, **verdict.model_dump()))
    job.status = "eligible" if verdict.eligible else "not_eligible"
    return job.status


def run_once() -> dict:
    init_db()
    stats = {"found": 0, "judged": 0, "eligible": 0, "notified": 0, "filtered": 0, "errors": 0}
    with httpx.Client(headers=HEADERS, timeout=20, follow_redirects=True) as client:
        with session_scope() as session:
            ensure_default_profile(session)
            stats["found"] = collect_new_jobs(session, client)

        with session_scope() as session:
            profile = effective_profile(session)  # profile.yaml + blocked companies from the dashboard
            pending = session.scalars(
                select(Job).where(Job.status == "new").order_by(Job.found_at.desc()).limit(MAX_NEW_JOBS_PER_RUN)
            ).all()
            for job in pending:
                try:
                    status = process_job(session, job, client, profile)
                except AllProvidersFailed as e:
                    log.error("no LLM available, stopping this run: %s", e)
                    stats["errors"] += 1
                    break
                except Exception:
                    log.exception("job %s failed", job.linkedin_id)
                    stats["errors"] += 1
                    continue
                session.commit()  # keep progress if a later job fails
                if status == "filtered":
                    stats["filtered"] += 1
                elif status in ("eligible", "not_eligible"):
                    stats["judged"] += 1

        with session_scope() as session:
            to_send = session.scalars(
                select(Job).where(Job.status == "eligible").order_by(Job.found_at.desc())
                .limit(MAX_NOTIFICATIONS_PER_RUN)
            ).all()
            stats["eligible"] = len(to_send)
            for job in to_send:
                if send_job(job, job.evaluation):
                    job.status = "notified"
                    stats["notified"] += 1
    log.info("run finished: %s", stats)
    return stats


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    run_once()
