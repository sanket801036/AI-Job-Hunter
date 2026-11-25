"""Single-user login. The password lives in DASHBOARD_PASSWORD; a signed cookie keeps
me logged in. No user table needed for one person."""
import hashlib
import hmac
import secrets
import time

from fastapi import Request

from app.config import get_settings

COOKIE = "jh_session"
MAX_AGE = 30 * 24 * 3600  # 30 days


def _key() -> bytes:
    s = get_settings()
    # the signing key changes whenever the password changes, which logs out old sessions
    return hashlib.sha256(f"{s.webhook_secret}|{s.dashboard_password}".encode()).digest()


def make_token() -> str:
    issued = str(int(time.time()))
    sig = hmac.new(_key(), issued.encode(), hashlib.sha256).hexdigest()
    return f"{issued}.{sig}"


def token_ok(token: str | None) -> bool:
    if not token or "." not in token:
        return False
    issued, sig = token.split(".", 1)
    good = hmac.new(_key(), issued.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, good):
        return False
    return issued.isdigit() and time.time() - int(issued) < MAX_AGE


def password_ok(given: str) -> bool:
    real = get_settings().dashboard_password
    return bool(real) and secrets.compare_digest(given.encode(), real.encode())


def is_logged_in(request: Request) -> bool:
    return token_ok(request.cookies.get(COOKIE))
