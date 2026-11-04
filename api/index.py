"""Vercel serverless entry point for the KIFARU PORTOS API.

Vercel's Python runtime exposes the ASGI `app` object below. Limitations of this hosting mode (documented, not hidden):
  * no WebSockets — the web app falls back to polling /api/v1/events/recent (VITE_WS_DISABLED=1 at build time);
  * no background workers — forecasts/predictions run on request (e.g. POST /shipments/{id}/predict-release);
  * the filesystem is ephemeral — unless KIFARU_DATABASE_URL points at a hosted PostgreSQL, a per-instance SQLite
    database is created in /tmp and seeded on cold start, so data does not persist and may differ between instances.
    This is a DEMO configuration; the production design is ECS + RDS (see docs/02-architecture/cloud-architecture.md).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for rel in ("apps/api", "packages/wim_dsp", "packages/ai_agents", "packages/simulation"):
    p = str(ROOT / rel)
    if p not in sys.path:
        sys.path.insert(0, p)

os.environ.setdefault("KIFARU_ENV", "dev")
os.environ.setdefault("KIFARU_LOCAL_OBJECT_DIR", "/tmp/kifaru-objects")
if not os.environ.get("KIFARU_DATABASE_URL"):
    # Vercel Marketplace Postgres integrations (Neon, Supabase, ...) inject one of these automatically.
    hosted = next((os.environ[k] for k in ("DATABASE_URL", "POSTGRES_URL", "POSTGRES_PRISMA_URL", "DATABASE_URL_UNPOOLED") if os.environ.get(k)), None)
    if hosted:
        if hosted.startswith("postgres://"):
            hosted = "postgresql+psycopg://" + hosted[len("postgres://"):]
        elif hosted.startswith("postgresql://"):
            hosted = "postgresql+psycopg://" + hosted[len("postgresql://"):]
        os.environ["KIFARU_DATABASE_URL"] = hosted
    else:
        os.environ["KIFARU_DATABASE_URL"] = "sqlite:////tmp/kifaru.db"

from sqlalchemy import select  # noqa: E402

from kifaru.db import ensure_schemas, get_engine, get_sessionmaker  # noqa: E402
from kifaru.main import create_app  # noqa: E402
from kifaru.models import Base, User  # noqa: E402


def _bootstrap() -> None:
    """Create tables and seed demo data when the database is empty (idempotent, runs once per cold start)."""
    engine = get_engine()
    ensure_schemas(engine)
    Base.metadata.create_all(engine)
    with get_sessionmaker()() as db:
        if db.execute(select(User).limit(1)).scalar_one_or_none() is None:
            from kifaru.seed import seed

            seed(verbose=False)


_bootstrap()
app = create_app()
