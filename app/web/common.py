"""Shared pieces for the dashboard routes: templates, date filters, DB session."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import Request
from fastapi.templating import Jinja2Templates

from app.db import SessionLocal

BASE = Path(__file__).parent
templates = Jinja2Templates(directory=BASE / "templates")

IST = timezone(timedelta(hours=5, minutes=30))


def ist(dt: datetime | None, fmt: str = "%d %b %Y, %I:%M %p") -> str:
    """UTC from the database -> Indian time for display."""
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(IST).strftime(fmt)


def ago(dt: datetime | None) -> str:
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    mins = int((datetime.now(timezone.utc) - dt).total_seconds() // 60)
    if mins < 60:
        return f"{max(mins, 0)} min ago"
    if mins < 24 * 60:
        return f"{mins // 60} h ago"
    return f"{mins // (24 * 60)} d ago"


def parse_local_datetime(value: str) -> datetime | None:
    """<input type="datetime-local"> gives Indian local time without a zone."""
    if not value:
        return None
    return datetime.fromisoformat(value).replace(tzinfo=IST).astimezone(timezone.utc)


def local_input(dt: datetime | None) -> str:
    """Value for a datetime-local input."""
    return ist(dt, "%Y-%m-%dT%H:%M") if dt else ""


templates.env.filters["ist"] = ist
templates.env.filters["ago"] = ago
templates.env.filters["local_input"] = local_input


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def render(request: Request, name: str, **ctx):
    ctx.setdefault("active", "")
    return templates.TemplateResponse(request, name, ctx)
