"""Skip lists = profile.yaml defaults + what I add from the dashboard."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_profile
from app.models import Company, Setting

EXTRA_TITLE_WORDS = "extra_title_skip_words"


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
    return profile
