"""KIFARU PORTOS API application factory."""
from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import get_settings
from .routers import (
    admin,
    auth,
    backhaul,
    environment,
    fleet,
    integrations,
    notifications,
    queue,
    shipments,
    stations,
    tickets,
    weighing,
    ws,
)

structlog.configure(processors=[structlog.processors.TimeStamper(fmt="iso"), structlog.processors.add_log_level, structlog.processors.JSONRenderer()])
log = structlog.get_logger("kifaru.api")

API_DESCRIPTION = """
**Kenya Intelligent Freight, Access, Routing & Unified Logistics Platform** — backend API.

* Rolling clearance (WIM pre-screen -> deterministic GREEN/AMBER/RED). The static scale remains the legal reference.
* Digital cargo passport, signed weighing tickets with QR verification, hash-chained ledger.
* Queue forecasting and slot booking, backhaul marketplace, environmental estimates (modelled).
* Every record carries `source` = `live` | `simulated` | `replay`. Simulated data is never presented as live.
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    logging.basicConfig(level=s.log_level)
    log.info("startup", env=s.env, db="sqlite" if s.is_sqlite else "postgresql")
    from .events import bus

    if bus.start_redis_subscriber() is not None:
        log.info("redis_subscriber_started")
    yield
    log.info("shutdown")


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(title=s.app_name, version=s.api_version, description=API_DESCRIPTION, lifespan=lifespan,
                  docs_url="/docs", redoc_url="/redoc", openapi_url="/openapi.json")
    app.add_middleware(CORSMiddleware, allow_origins=s.cors_origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

    @app.middleware("http")
    async def _timing_and_headers(request: Request, call_next):
        t0 = time.perf_counter()
        resp = await call_next(request)
        resp.headers["X-Response-Time-ms"] = f"{(time.perf_counter() - t0) * 1000:.1f}"
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "no-referrer"
        if s.env in ("staging", "prod"):
            resp.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
        return resp

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        log.exception("unhandled", path=request.url.path)
        return JSONResponse({"detail": "Internal server error"}, status_code=500)

    prefix = "/api/v1"
    for r in (auth, fleet, stations, weighing, tickets, shipments, queue, backhaul, notifications, environment, integrations, admin):
        app.include_router(r.router, prefix=prefix)
    app.include_router(ws.router)

    @app.get("/health", tags=["ops"])
    def health():
        return {"status": "ok", "env": s.env, "version": s.api_version}

    @app.get("/ready", tags=["ops"])
    def ready():
        from sqlalchemy import text

        from .db import get_engine

        with get_engine().connect() as c:
            c.execute(text("SELECT 1"))
        return {"status": "ready"}

    return app


app = create_app()
