# KIFARU PORTOS

**Kenya Intelligent Freight, Access, Routing & Unified Logistics Platform** — an AI-assisted smart-port and freight
logistics ecosystem built around highway-speed weigh-in-motion (WIM) rolling clearance for the Port of Mombasa,
Mariakani and the Northern Corridor.

| | |
|---|---|
| Status (2026-11-04) | Phases 1–5 implemented and tested locally; Phase 6 hardware designed (not built); Phase 7 pilot procedure written. **No cloud deployment has been performed** — it requires the owner's AWS account (see `docs/06-operations/deployment-guide.md`). |
| Honesty rules | Every weighing record carries `source` = `live` / `simulated` / `replay`; simulated data is never shown as live. Government and commercial adapters are `mock` until authorised credentials are configured. Environmental figures are labelled *modelled*. Accuracy/latency targets remain targets until measured in Phase 7. |
| Legal note | Axle/GVM limits in `apps/api/kifaru/services/limits.py` are configuration flagged for verification against the current EAC Vehicle Load Control Act schedule. The static scale remains the legal reference; WIM only pre-screens. |

## Repository layout

```
kifaru-portos/
├── apps/
│   ├── api/            FastAPI backend: auth/RBAC/MFA, fleet, stations, WIM ingest + simulator, deterministic
│   │                   clearance engine, signed tickets + QR, hash-chained ledger, cargo passport, queue/slots,
│   │                   backhaul marketplace, environment, integrations, admin, WebSocket, workers (MQTT/SQS/jobs)
│   ├── web/            React 18 + TypeScript + Vite + Tailwind: 7 role dashboards, public ticket verify, Three.js twin
│   └── mobile/         Flutter driver (hands-free) + cargo-owner app (not compiled here: no Flutter SDK)
├── packages/
│   ├── wim_dsp/        Reference WIM signal generation + processing (axle detection, speed, loads, uncertainty, health)
│   ├── ai_agents/      10 cooperating advisory agents + orchestrator (forecast, backhaul, release, environment, …)
│   └── simulation/     SimPy weighbridge/port model, 11 scenarios, comparison reports, SUMO adapter
├── edge/gateway/       Roadside gateway (Python): DAQ client, identity adapters, local clearance mirror,
│                       SQLite store-and-forward outbox, MQTT/HTTP uplink, VMS driver
├── firmware/
│   ├── stm32-wim-daq/  STM32H743 + ADS131M08 acquisition/DSP firmware (CMake, FreeRTOS; not compiled here)
│   └── esp32-aux/      ESP-IDF environmental/cabinet node
├── infra/
│   ├── terraform/      AWS af-south-1: 12 modules, dev/staging/prod roots, bootstrap (validated, not applied)
│   └── docker/         docker-compose (PostgreSQL, Redis, EMQX, api, web, workers)
├── .github/workflows/  CI (lint, tests, web build, terraform validate, security scans) and OIDC deploy pipeline
└── docs/
    ├── 01-requirements/  source review (original RCS document missing — see 00-source-review.md), RTM
    ├── 02-architecture/  system, cloud, database ERD, hardware, tech stack, roadmap
    ├── 03-hardware/      sensor architecture, analog front-end calculations, power/protection, enclosure,
    │                     communications, calibration, lab rig build guide, BOM
    ├── 04-security/      threat model, controls catalogue, DPIA (Kenya DPA 2019), incident response plan
    ├── 05-report/        42-section engineering report
    └── 06-operations/    deployment guide, DR runbook, backups, local development, API documentation
                          (+ openapi.json), simulation guide, emissions model, maintenance, user manuals,
                          USSD/SMS spec, pilot shadow-mode plan, verified test results
```

## Quick start (local, no Docker)

Prerequisites: Python 3.12, Node 20+ (26 used here), git.

```bash
# 1. Python environment and packages
python -m venv .venv
.venv/Scripts/python -m pip install -e packages/wim_dsp -e packages/ai_agents -e packages/simulation
.venv/Scripts/python -m pip install -e "apps/api[dev]" email-validator

# 2. Backend (SQLite by default; see apps/api/.env.example for PostgreSQL/Redis/MQTT)
cd apps/api
../../.venv/Scripts/python -m alembic upgrade head
../../.venv/Scripts/python -m kifaru.seed          # demo data; prints the demo accounts and a generated password once
../../.venv/Scripts/python -m uvicorn kifaru.main:app --reload --port 8000   # http://localhost:8000/docs

# 3. Frontend (second terminal)
cd apps/web && npm install && npm run dev           # http://localhost:5173 (proxies /api and /ws to :8000)

# 4. Optional workers (third terminal)
cd apps/api && ../../.venv/Scripts/python -m kifaru.worker --every 5     # forecasts, predictions, incidents, security scan
cd apps/api && ../../.venv/Scripts/python -m kifaru.ingest               # MQTT/SQS device ingest (needs a broker)

# 5. Edge gateway simulator (feeds the API like a real lane would)
cd edge/gateway && ../../.venv/Scripts/python -m kifaru_gateway.main --simulate --rate 2
```

Docker Compose path (PostgreSQL + Redis + EMQX + api + web): `docs/06-operations/local-development.md`.

## Tests

```bash
cd apps/api            && ../../.venv/Scripts/python -m pytest -q    # 57 tests: API, clearance rules, security, workers
cd packages/wim_dsp    && ../../.venv/Scripts/python -m pytest -q    # 24 tests: signal pipeline
cd packages/ai_agents  && ../../.venv/Scripts/python -m pytest -q    # 8 tests: agents + orchestrator
cd packages/simulation && ../../.venv/Scripts/python -m pytest -q    # 15 tests: SimPy model + reports
cd edge/gateway        && ../../.venv/Scripts/python -m pytest -q    # outbox, clearance mirror, frame parser
cd apps/web            && npm run build                               # TypeScript + Vite production build
python -m ruff check apps/api packages                                # lint (config in ruff.toml)
```

Run the API suite against PostgreSQL: `KIFARU_TEST_DATABASE_URL=postgresql+psycopg://user:pass@host/db pytest -q`.
Verified results and their caveats: `docs/06-operations/test-results.md`.

## Demo accounts (local only)

The seed command creates one account per role and prints the e-mail addresses together with a password that is
generated for that run (or taken from `KIFARU_SEED_PASSWORD`). Credentials are deliberately not listed in this
repository. Production seeding never creates demo users.

## What the owner must provide to go live

1. AWS account (Organization recommended), Route 53 hosted zone and domain, GitHub repository for OIDC deploys.
2. SMS (Africa's Talking) and email (SES) accounts; telematics/fleet API credentials where available.
3. Decisions on data-protection registration with the ODPC and counsel review of `docs/04-security/dpia.md`.
4. Confirmation of the legal axle-load schedule and tolerance policy with KeNHA (`services/limits.py`).
5. Weighbridge site access and regulator agreement for the shadow-mode pilot (`docs/06-operations/pilot-shadow-mode.md`).

## Licence

Proprietary — KIFARU PORTOS project. All rights reserved unless otherwise agreed in writing.
