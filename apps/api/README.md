# KIFARU PORTOS — Backend API

FastAPI service implementing rolling clearance (WIM pre-screen → deterministic GREEN/AMBER/RED), the digital cargo
passport, signed weighing tickets, hash-chained ledger, queue/slot management, backhaul marketplace, environmental
estimates, integration adapters (mock by default) and the admin surface. See `docs/02-architecture/` for the design.

## Quick start (bare metal, SQLite)

```bash
# from the repo root (Windows: use .venv/Scripts/python.exe)
python -m venv .venv
.venv/Scripts/python -m pip install -e packages/wim_dsp -e packages/ai_agents -e packages/simulation
.venv/Scripts/python -m pip install -e "apps/api[dev]" email-validator
cd apps/api
cp .env.example .env                       # edit if needed
../../.venv/Scripts/python -m alembic upgrade head
../../.venv/Scripts/python -m kifaru.seed  # demo data; prints demo accounts
../../.venv/Scripts/python -m uvicorn kifaru.main:app --reload --port 8000
```

Open http://localhost:8000/docs. Demo password for all seeded accounts: `***REMOVED***` (dev only).

## PostgreSQL

Set `KIFARU_DATABASE_URL=postgresql+psycopg://user:pass@host:5432/kifaru` and run `alembic upgrade head`; the migration
creates the `core`, `pii` and `ts` schemas. The Docker Compose stack in `infra/docker/` does this automatically.

## Tests

```bash
cd apps/api && ../../.venv/Scripts/python -m pytest -q          # API + clearance engine (SQLite)
cd packages/wim_dsp && ../../.venv/Scripts/python -m pytest -q   # signal pipeline
cd packages/ai_agents && ../../.venv/Scripts/python -m pytest -q # agents + orchestrator
```

## Layout

```
kifaru/
  main.py            app factory, middleware, routers, /health /ready
  config.py          pydantic-settings (env prefix KIFARU_)
  db.py              engine/session; schema translation for SQLite
  security.py        Argon2id, JWT, TOTP, Ed25519
  deps.py            auth principal, RBAC + MFA gating, audit, rate limit, org scoping
  events.py          event catalogue + in-process/Redis bus
  models/            SQLAlchemy models (core / pii / ts schemas)
  services/          clearance_engine (deterministic), limits (legal config), identity fusion,
                     weighing_service (lane-pass orchestration), simulator, tickets, ledger, queue_forecast
  routers/           auth, fleet, stations, weighing, tickets, shipments, queue, backhaul,
                     notifications, environment, integrations, admin, ws
  workers/           MQTT/SQS ingest and periodic jobs (forecasts, release prediction, incidents)
  seed.py            idempotent demo seed
alembic/             migrations
tests/               pytest suites (API flow, clearance rules, workers)
```

## Key invariants

* `source` (`live` | `simulated` | `replay`) is stored on every weighing event and surfaced in every response.
* The clearance engine (`services/clearance_engine.py`) is a pure function: all rules evaluated, evidence hash returned;
  any blocking quality flag or expired calibration prevents GREEN. AI agents are advisory inputs only.
* Static-scale results are the legal reference; `static_certified` tickets are only issued from the operator's static
  verification endpoint.
* Legal axle/GVM limits live in `services/limits.py` with a version string stored on every decision — **verify against
  the current EAC Vehicle Load Control Act schedule before any pilot**.
* Government/commercial adapters are `mock` until real credentials and base URLs are configured by a platform admin.
