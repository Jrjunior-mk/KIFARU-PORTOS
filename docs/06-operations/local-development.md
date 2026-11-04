# KIFARU PORTOS — Local Development

Two supported paths:

| Path | Use when | Stack |
|---|---|---|
| **A. Bare metal (venv + SQLite)** | fastest loop for API/DSP/AI work and running the test-suite | Python 3.12, SQLite (WAL), no Redis/MQTT |
| **B. Docker Compose (full stack)** | parity with the cloud: PostgreSQL schemas, Redis fan-out, MQTT broker, built images | Docker ≥ 24 with Compose v2 |

The Compose stack uses **the same `apps/api/Dockerfile`** that CI pushes to ECR. Note: at the time of writing no Docker
daemon was available on the authoring machine, so the Compose file and Dockerfile are reviewed but **not yet built**; the
CI `docker` job in `.github/workflows/ci.yml` builds and smoke-tests the image on every push.

---

## A. Bare metal

```bash
# from the repo root (Windows: use Git Bash or PowerShell equivalents)
python -m venv .venv
source .venv/bin/activate            # PowerShell: .venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e packages/wim_dsp -e packages/ai_agents -e packages/simulation
pip install -e "apps/api[dev]" email-validator

cd apps/api
cp .env.example .env                 # SQLite by default; edit KIFARU_* as needed
alembic upgrade head                 # creates kifaru_dev.db (schemas are mapped to the default namespace on SQLite)
python -m kifaru.seed                # demo orgs/users/stations; prints the accounts
uvicorn kifaru.main:app --reload --port 8000
```

* API: http://localhost:8000 — OpenAPI at `/docs`, health at `/health`, readiness at `/ready`.
* WebSocket: `ws://localhost:8000/ws/events?token=<access token>`.
* Tests: `pytest -q` in `apps/api`, `packages/wim_dsp`, `packages/ai_agents`. Lint: `ruff check apps/api packages`.
* Object storage: local folder `./objects` (`KIFARU_LOCAL_OBJECT_DIR`).
* Redis and MQTT are optional here; the event bus falls back to in-process fan-out when `KIFARU_REDIS_URL` is unset.

Web (when `apps/web` lands): `cd apps/web && npm ci && npm run dev` → http://localhost:5173 (Vite proxies `/api` to 8000
if configured in `vite.config.ts`; otherwise set `VITE_API_BASE_URL=http://localhost:8000`).

---

## B. Docker Compose

```bash
cp infra/docker/.env.compose.example infra/docker/.env.compose      # edit secrets if you like; defaults are local-only
docker compose --env-file infra/docker/.env.compose -f infra/docker/docker-compose.yml up --build
```

What starts:

| Service | Image | Host port(s) | Notes |
|---|---|---|---|
| `postgres` | `postgres:16` | 5432 | init SQL `infra/docker/postgres/init/01-schemas.sql` creates schemas `core`, `pii`, `ts`, `pgcrypto`, `pg_stat_statements`; data in volume `pgdata` |
| `redis` | `redis:7` | 6379 | AOF persistence, `volatile-lru` |
| `emqx` | `emqx:5` | 1883 (MQTT), 8883 (MQTT/TLS, EMQX self-signed cert), 8083 (MQTT over WS), 18083 (dashboard: `admin` / `EMQX_DASHBOARD_PASSWORD`) | anonymous access **enabled for local only** |
| `api` | built from `apps/api/Dockerfile` | 8000 | runs `alembic upgrade head` → `python -m kifaru.seed --quiet` (unless `KIFARU_SEED_DEMO=false`) → `uvicorn … --workers 2`; non-root user `kifaru` (uid 10001); `/data/objects` volume |
| `web` | built from `apps/web/Dockerfile` (nginx :80) | 5173 | build args `VITE_API_BASE_URL`, `VITE_WS_BASE_URL` point at the host API port |
| `worker`, `ingest` | same api image, **profile `workers`** | — | `python -m kifaru.worker` / `kifaru.ingest`; disabled until those entrypoints exist in the app: `docker compose --profile workers up` |

Useful commands:

```bash
docker compose -f infra/docker/docker-compose.yml logs -f api
docker compose -f infra/docker/docker-compose.yml exec api alembic current
docker compose -f infra/docker/docker-compose.yml exec api python -m kifaru.seed      # re-seed (idempotent)
docker compose -f infra/docker/docker-compose.yml exec postgres psql -U kifaru -d kifaru -c '\dn'
docker compose -f infra/docker/docker-compose.yml down -v                              # wipe volumes
```

Publishing a test MQTT event to the local broker (what a station gateway would send):

```bash
docker run --rm --network kifaru_default eclipse-mosquitto mosquitto_pub -h emqx -p 1883 \
  -t kifaru/stations/gw-mrk-l1/events -m '{"event_id":"01J…","type":"truck.detected","payload":{}}'
```

Building the API image alone (from the repo root; BuildKit picks up `apps/api/Dockerfile.dockerignore`):

```bash
docker build -f apps/api/Dockerfile -t kifaru/api:local .
docker run --rm -p 8000:8000 -e KIFARU_DATABASE_URL=sqlite:////tmp/k.db -e KIFARU_JWT_SECRET=local-only-secret-16+ kifaru/api:local
```

---

## Ports summary

| Port | Service |
|---|---|
| 8000 | API (REST + WS) |
| 5173 | Web (Vite dev server or nginx container) |
| 5432 | PostgreSQL |
| 6379 | Redis |
| 1883 / 8883 / 8083 | MQTT / MQTT-TLS / MQTT-WS (EMQX) |
| 18083 | EMQX dashboard |

---

## Demo accounts (seed data)

Created by `python -m kifaru.seed` (idempotent). **Password for all: `***REMOVED***`** (`DEMO_PASSWORD` in
`apps/api/kifaru/seed.py`). Local/dev/staging only — production never runs the seed (the `ecs` module refuses to create
the seed task for `env = prod`).

| E-mail | Role(s) | Organisation |
|---|---|---|
| `admin@demo.invalid` | platform_admin | KIFARU PORTOS Platform |
| `control@demo.invalid` | port_controller | Platform |
| `operator@demo.invalid` | weighbridge_operator | Platform |
| `auditor@demo.invalid` | auditor | Platform |
| `dispatch@transporter-a.invalid` | transporter_admin, dispatcher | Simba Transporters Ltd |
| `driver1@transporter-a.invalid` | driver | Simba Transporters Ltd |
| `dispatch@transporter-b.invalid` | transporter_admin | Pwani Haulers |
| `owner@cargo-a.invalid` | cargo_owner | Mama Mboga Traders |
| `owner@cargo-b.invalid` | cargo_owner | Nakuru Grains Ltd |
| `wh@warehouse-a.invalid` | warehouse_manager | Nairobi ICD Warehousing |

Privileged roles (`platform_admin`, `weighbridge_operator`, `port_controller`, `auditor`) require TOTP MFA enrolment on
first login (`KIFARU_MFA_REQUIRED_ROLES`). Seeded stations: `MRK` Mariakani, `ATH` Athi River, `MBS-GATE18` Mombasa Gate
18, `GLG` Gilgil, each with lanes 1–2 (`gw-<code>-l<n>` device ids) and a static lane where applicable. All seeded
operational data is tagged `source=simulated`.

---

## Environment variables

See `apps/api/.env.example` (bare metal) and `infra/docker/.env.compose.example` (Compose). All settings use the
`KIFARU_` prefix (`apps/api/kifaru/config.py`). Minimum for a non-SQLite run: `KIFARU_DATABASE_URL`, `KIFARU_JWT_SECRET`
(≥ 16 chars); staging/prod additionally require `KIFARU_SIGNING_SEED_B64`.
