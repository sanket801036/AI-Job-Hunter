"""Decide whether a job is worth my time.

Two layers:
1. Cheap fixed rules first (skip-listed company, Staff/Principal/Lead titles). These
   need no LLM call.
2. The LLM reads the JD against my profile (and the resume of the search profile,
   if one is uploaded) and returns a structured verdict. Fixed rules are applied on top
   again, so the LLM can never mark a 10-year role as eligible.
"""
import logging
import re

from pydantic import BaseModel, Field, field_validator

from app.config import get_profile
from app.llm.client import complete_json

log = logging.getLogger(__name__)


class Verdict(BaseModel):
    is_relevant: bool = Field(description="the role matches the kind of job I search for")
    min_years: int | None = None
    max_years: int | None = None
    seniority: str = "unknown"  # junior | mid | senior | lead | principal | unknown
    eligible: bool = False
    match_score: int = Field(0, ge=0, le=100)
    matched_skills: list[str] = []
    missing_skills: list[str] = []
    red_flags: list[str] = []
    reason: str = ""

    @field_validator("match_score", mode="before")
    @classmethod
    def clamp(cls, v):
        try:
            return max(0, min(100, int(v)))
        except (TypeError, ValueError):
            return 0


def pre_filter(title: str, company: str, profile: dict | None = None) -> str | None:
    """Reason to skip without asking the LLM, or None to continue."""
    profile = profile or get_profile()
    company_l = company.lower()
    for name in profile.get("skip_companies", []):
        if name.lower() in company_l:
            return f"company on skip list ({name})"
    for word in profile.get("titles_skip", []):
        if re.search(rf"\b{re.escape(word)}\b", title, re.I):
            return f"title says {word}"
    return None


SYSTEM = """You screen job postings for one candidate. Read the job description and the
candidate profile, then answer with a single JSON object and nothing else:
{
  "is_relevant": bool,        // is this the kind of role in "Looking for"?
  "min_years": int|null,      // minimum years of experience the JD asks for
  "max_years": int|null,      // upper end if a range is given
  "seniority": "junior|mid|senior|lead|principal|unknown",
  "eligible": bool,           // could the candidate realistically get shortlisted?
  "match_score": int,         // 0-100 fit between JD and candidate
  "matched_skills": [str],    // JD skills the candidate has (max 8)
  "missing_skills": [str],    // important JD skills the candidate lacks (max 6)
  "red_flags": [str],         // e.g. "contract role", "night shift", "10+ years", "unpaid", "relocation abroad"
  "reason": str               // one short sentence
}
Rules: years asked must be at most the candidate's acceptable maximum for "eligible".
A skill counts as matched if it appears in Skills, the resume or the About section, including
close equivalents (e.g. "retries" covers "error handling/retries"). Do not list it as missing then.
If the JD gives no years, judge by seniority and responsibilities. Be strict and honest."""


def _user_prompt(title: str, company: str, location: str, description: str,
                 looking_for: str, resume_text: str, profile: dict) -> str:
    skills = ", ".join(profile.get("skills", []))
    resume = f"\nResume:\n{resume_text[:6000]}" if resume_text else ""
    about = profile.get("about_me", "")
    about = f"\nAbout the candidate (written by them, trust it): {about[:2000]}" if about else ""
    return (
        f"Looking for: {looking_for}\n"
        f"Candidate: {profile.get('experience_years')} years of experience, "
        f"acceptable maximum asked: {profile.get('max_years_ok')} years.\n"
        f"Skills: {skills}\n"
        f"Preferred locations: {', '.join(profile.get('locations_ok', []))}"
        f"{about}{resume}\n\n"
        f"Job title: {title}\nCompany: {company}\nLocation: {location}\n"
        f"Job description:\n{description[:12000]}"
    )


def apply_rules(v: Verdict, profile: dict) -> Verdict:
    """Fixed limits the LLM cannot override."""
    max_ok = profile.get("max_years_ok", 5)
    if v.min_years is not None and v.min_years > max_ok:
        v.eligible = False
        v.red_flags.append(f"asks {v.min_years}+ years")
    if v.seniority in ("lead", "principal"):
        v.eligible = False
    if not v.is_relevant:
        v.eligible = False
    return v


def judge(title: str, company: str, location: str, description: str,
          looking_for: str = "AI Engineer", resume_text: str = "",
          profile: dict | None = None) -> tuple[Verdict, str]:
    """Returns (verdict, provider name). Raises AllProvidersFailed if no LLM answered."""
    profile = profile or get_profile()
    prompt = _user_prompt(title, company, location, description, looking_for, resume_text, profile)
    verdict, provider = complete_json(SYSTEM, prompt, validate=Verdict.model_validate)
    return apply_rules(verdict, profile), provider
