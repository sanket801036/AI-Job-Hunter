"""New jobs from LinkedIn's public (logged-out) job search.

Uses the same endpoint the logged-out jobs page calls when you scroll. No account,
no cookies. Each page returns up to 10 job cards as HTML.
"""
import logging
import random
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone

import httpx
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

SEARCH_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}
PAGE_SIZE = 10


@dataclass
class JobCard:
    linkedin_id: str
    title: str
    company: str
    location: str
    url: str
    posted_on: date | None

    @property
    def posted_at(self) -> datetime | None:
        if self.posted_on is None:
            return None
        return datetime(self.posted_on.year, self.posted_on.month, self.posted_on.day, tzinfo=timezone.utc)


def _text(node) -> str:
    return " ".join(node.get_text(" ").split()) if node else ""


def parse_cards(html: str) -> list[JobCard]:
    """Turn one page of search results into job cards."""
    soup = BeautifulSoup(html, "lxml")
    cards = []
    for div in soup.select("div[data-entity-urn]"):
        m = re.search(r"jobPosting:(\d+)", div.get("data-entity-urn", ""))
        if not m:
            continue
        job_id = m.group(1)
        link = div.select_one("a.base-card__full-link")
        posted = div.select_one("time")
        posted_on = None
        if posted and posted.get("datetime"):
            try:
                posted_on = date.fromisoformat(posted["datetime"])
            except ValueError:
                pass
        cards.append(
            JobCard(
                linkedin_id=job_id,
                title=_text(div.select_one(".base-search-card__title")),
                company=_text(div.select_one(".base-search-card__subtitle")),
                location=_text(div.select_one(".job-search-card__location")),
                # tracking params removed so the link is short and stable
                url=f"https://www.linkedin.com/jobs/view/{job_id}/" if not link else link["href"].split("?")[0],
                posted_on=posted_on,
            )
        )
    return cards


# HTTP status of the most recent search request; 999 or 429 means LinkedIn is blocking us.
last_status: int | None = None


def search(
    keyword: str,
    hours: int = 6,
    work_types: str = "1,2,3",
    geo_id: str = "102713980",
    pages: int = 2,
    client: httpx.Client | None = None,
    under_10: bool = False,
) -> list[JobCard]:
    """Jobs posted in the last `hours` for one keyword. Stops early when a page is
    short (no more results) and backs off once if LinkedIn rate limits us."""
    global last_status
    own_client = client is None
    client = client or httpx.Client(headers=HEADERS, timeout=20, follow_redirects=True)
    found: list[JobCard] = []
    try:
        for page in range(pages):
            params = {
                "keywords": keyword,
                "geoId": geo_id,
                "f_TPR": f"r{hours * 3600}",
                "f_WT": work_types,
                "sortBy": "DD",  # newest first
                "start": page * PAGE_SIZE,
            }
            if under_10:
                params["f_EA"] = "true"  # LinkedIn's "Under 10 applicants" filter
            resp = client.get(SEARCH_URL, params=params)
            for wait in (15, 30, 45):  # LinkedIn often lets the next try through
                if resp.status_code != 429:
                    break
                log.warning("rate limited on %r page %d, retrying in %ds", keyword, page, wait)
                time.sleep(wait)
                resp = client.get(SEARCH_URL, params=params)
            last_status = resp.status_code
            if resp.status_code != 200:
                log.warning("search %r page %d returned HTTP %d", keyword, page, resp.status_code)
                break
            cards = parse_cards(resp.text)
            found.extend(cards)
            if len(cards) < PAGE_SIZE:
                break
            time.sleep(random.uniform(2, 5))  # do not hammer the endpoint
    finally:
        if own_client:
            client.close()
    return found


def dedupe(cards: list[JobCard], seen_ids: set[str]) -> list[JobCard]:
    """Drop jobs already in the database and duplicates across keywords."""
    fresh, ids = [], set(seen_ids)
    for c in cards:
        if c.linkedin_id not in ids:
            ids.add(c.linkedin_id)
            fresh.append(c)
    return fresh
