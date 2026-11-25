"""Full job details from LinkedIn's public job page: description, criteria, applicants,
and how to apply (Easy Apply on LinkedIn, or the company's own site).

When the job uses the company's site, LinkedIn often hides the real link from
logged-out visitors. In that case `apply_url` stays empty and the LinkedIn job link
is the way in.
"""
import html
import logging
import re
import time
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlparse

import httpx
from bs4 import BeautifulSoup

from app.linkedin.search import HEADERS

log = logging.getLogger(__name__)

DETAIL_URL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"


@dataclass
class JobDetail:
    description: str = ""
    seniority: str = ""
    employment_type: str = ""
    job_function: str = ""
    industries: str = ""
    applicants: str = ""
    posted_ago: str = ""
    easy_apply: bool | None = None  # None = could not tell
    apply_url: str = ""
    criteria: dict = field(default_factory=dict)


def _clean(text: str) -> str:
    return " ".join(text.split())


def _description_text(node) -> str:
    """Keep line breaks between paragraphs and bullet points so the JD stays readable."""
    if node is None:
        return ""
    for br in node.find_all("br"):
        br.replace_with("\n")
    for li in node.find_all("li"):
        li.insert_before("\n- ")
    for block in node.find_all(["p", "ul", "ol", "h1", "h2", "h3", "strong"]):
        block.insert_after("\n")
    lines = [" ".join(line.split()) for line in node.get_text().splitlines()]
    out, blank = [], False
    for line in lines:
        if line:
            out.append(line)
            blank = False
        elif not blank and out:
            out.append("")
            blank = True
    return "\n".join(out).strip()


def _external_url(soup: BeautifulSoup) -> str:
    """Older pages carry the company link in a hidden <code id="applyUrl"> comment."""
    code = soup.find("code", id="applyUrl")
    if not code:
        return ""
    raw = html.unescape(code.decode_contents()).strip().strip("<!->").strip().strip('"')
    if not raw:
        return ""
    target = parse_qs(urlparse(raw).query).get("url")
    return target[0] if target else raw


def parse_detail(page: str) -> JobDetail:
    soup = BeautifulSoup(page, "lxml")
    d = JobDetail()

    d.description = _description_text(soup.select_one(".description__text .show-more-less-html__markup")
                                      or soup.select_one(".description__text"))

    for item in soup.select(".description__job-criteria-item"):
        key = _clean(item.select_one(".description__job-criteria-subheader").get_text()) \
            if item.select_one(".description__job-criteria-subheader") else ""
        val = _clean(item.select_one(".description__job-criteria-text").get_text()) \
            if item.select_one(".description__job-criteria-text") else ""
        if key:
            d.criteria[key] = val
    d.seniority = d.criteria.get("Seniority level", "")
    d.employment_type = d.criteria.get("Employment type", "")
    d.job_function = d.criteria.get("Job function", "")
    d.industries = d.criteria.get("Industries", "")

    applicants = soup.select_one(".num-applicants__caption, .num-applicants__figure")
    d.applicants = _clean(applicants.get_text()) if applicants else ""
    posted = soup.select_one(".posted-time-ago__text")
    d.posted_ago = _clean(posted.get_text()) if posted else ""

    if re.search(r"public_jobs_apply-link-onsite", page):
        d.easy_apply = True
    elif re.search(r"public_jobs_apply-link-offsite", page):
        d.easy_apply = False
        d.apply_url = _external_url(soup)
    return d


def fetch_detail(job_id: str, client: httpx.Client | None = None, retries: int = 2) -> JobDetail | None:
    """Download and parse one job. Returns None if LinkedIn keeps refusing."""
    own_client = client is None
    client = client or httpx.Client(headers=HEADERS, timeout=20, follow_redirects=True)
    try:
        for attempt in range(retries + 1):
            resp = client.get(DETAIL_URL.format(job_id=job_id))
            if resp.status_code == 200:
                return parse_detail(resp.text)
            if resp.status_code == 429 and attempt < retries:
                wait = 20 * (attempt + 1)
                log.warning("rate limited on job %s, waiting %ds", job_id, wait)
                time.sleep(wait)
                continue
            log.warning("job %s returned HTTP %d", job_id, resp.status_code)
            return None
    finally:
        if own_client:
            client.close()
    return None
