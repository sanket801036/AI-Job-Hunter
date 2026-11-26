"""Database engine and session. SQLite locally, Postgres (Neon) in production."""
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


def _make_engine():
    url = get_settings().database_url
    # Neon gives postgres:// or postgresql:// - use the psycopg 3 driver
    if url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://"):]
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    kwargs = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    return create_engine(url, **kwargs)


engine = _make_engine()
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def init_db() -> None:
    """Create tables that do not exist yet."""
    from app import models  # noqa: F401  registers the tables

    Base.metadata.create_all(engine)
    _add_missing_columns()


# Columns added after the first deploy. create_all() only creates new tables, so
# existing ones get these through a plain ALTER TABLE.
NEW_COLUMNS = [
    ("search_profiles", "under_10", "BOOLEAN NOT NULL DEFAULT FALSE"),
    ("jobs", "posted_ago", "VARCHAR(50) NOT NULL DEFAULT ''"),
]


def _add_missing_columns() -> None:
    from sqlalchemy import inspect, text

    insp = inspect(engine)
    with engine.begin() as conn:
        for table, column, ddl in NEW_COLUMNS:
            if column not in {c["name"] for c in insp.get_columns(table)}:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))


@contextmanager
def session_scope():
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def try_lock(name: str, seconds: int) -> bool:
    """Take a lease-style lock shared by every process using this database.
    Plain UPDATE/INSERT, so it works through Neon's connection pooler too."""
    import time

    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError

    now = time.time()
    params = {"n": name, "u": now + seconds, "now": now}
    with engine.begin() as conn:
        taken = conn.execute(text(
            "UPDATE run_locks SET locked_until = :u WHERE name = :n AND locked_until < :now"), params).rowcount
        if taken:
            return True
        if conn.execute(text("SELECT 1 FROM run_locks WHERE name = :n"), params).first():
            return False  # someone else holds it
    try:
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO run_locks (name, locked_until) VALUES (:n, :u)"), params)
        return True
    except IntegrityError:
        return False  # another process inserted it first


def release_lock(name: str) -> None:
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(text("UPDATE run_locks SET locked_until = 0 WHERE name = :n"), {"n": name})
