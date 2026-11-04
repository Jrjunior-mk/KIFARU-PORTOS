"""Database engine/session factory.

PostgreSQL uses three schemas: core, pii, ts. SQLite (tests, quick dev) has no schemas, so the schema
names are translated to the default namespace via `schema_translate_map`.
"""
from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .config import get_settings

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    global _engine, _SessionLocal
    if _engine is None:
        s = get_settings()
        kwargs: dict = {"echo": s.db_echo, "future": True}
        if s.is_sqlite:
            kwargs["connect_args"] = {"check_same_thread": False}
            _engine = create_engine(s.database_url, **kwargs).execution_options(
                schema_translate_map={"core": None, "pii": None, "ts": None}
            )

            @event.listens_for(_engine, "connect")
            def _sqlite_pragmas(dbapi_conn, _):  # pragma: no cover - trivial
                cur = dbapi_conn.cursor()
                cur.execute("PRAGMA foreign_keys=ON")
                cur.execute("PRAGMA journal_mode=WAL")
                cur.close()
        else:
            kwargs["pool_pre_ping"] = True
            kwargs["pool_size"] = 10
            _engine = create_engine(s.database_url, **kwargs)
        _SessionLocal = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)
    return _engine


def get_sessionmaker() -> sessionmaker[Session]:
    get_engine()
    assert _SessionLocal is not None
    return _SessionLocal


def get_db() -> Generator[Session, None, None]:
    db = get_sessionmaker()()
    try:
        yield db
    finally:
        db.close()


def reset_engine() -> None:
    """Used by tests to point at a fresh database."""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None


def ensure_schemas(engine: Engine) -> None:
    """Create the core/pii/ts schemas on PostgreSQL (no-op on SQLite, where they are translated away)."""
    if engine.dialect.name != "postgresql":
        return
    from sqlalchemy import text

    with engine.begin() as conn:
        for schema in ("core", "pii", "ts"):
            conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema}"))
