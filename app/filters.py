"""Skip lists = profile.yaml defaults + what I add from the dashboard."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_profile
from app.models import Company, Setting

EXTRA_TITLE_WORDS = "extra_title_skip_words"
EXTRA_SKILLS = "extra_skills"
ABOUT_ME = "about_me"


def get_setting(db: Session, key: str, default):
    row = db.get(Setting, key)
    return row.value if row is not None else default


def set_setting(db: Session, key: str, value) -> None:
    row = db.get(Setting, key)
    if row is None:
        db.add(Setting(key=key, value=value))
    else:
        row.value = value


def effective_profile(db: Session) -> dict:
    """profile.yaml with the dashboard's blocked companies and skip words merged in."""
    profile = dict(get_profile())
    blocked = db.scalars(select(Company.name).where(Company.blocked.is_(True))).all()
    profile["skip_companies"] = sorted({*profile.get("skip_companies", []), *blocked}, key=str.lower)
    extra = get_setting(db, EXTRA_TITLE_WORDS, [])
    profile["titles_skip"] = sorted({*profile.get("titles_skip", []), *extra}, key=str.lower)
    # skills I added from the dashboard because the LLM marked them missing
    known = {s.lower() for s in profile.get("skills", [])}
    profile["skills"] = list(profile.get("skills", [])) + [
        s for s in get_setting(db, EXTRA_SKILLS, []) if s.lower() not in known]
    profile["about_me"] = get_setting(db, ABOUT_ME, "")
    return profile


def add_skill(db: Session, skill: str) -> None:
    skill = skill.strip()
    if not skill:
        return
    current = get_setting(db, EXTRA_SKILLS, [])
    if skill.lower() not in {s.lower() for s in current}:
        set_setting(db, EXTRA_SKILLS, [*current, skill])
