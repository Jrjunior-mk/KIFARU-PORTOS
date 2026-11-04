# Verified Test Results — 2026-11-04 (local developer machine)

Everything below was actually executed on the development machine (Windows 11, Python 3.12.10, Node 26). Nothing here is
a production benchmark or a field measurement. Engineering targets from the Master Prompt §12 remain targets.

## 1. Automated test suites

| Suite | Command (from repo root, venv active) | Result |
|---|---|---|
| API + clearance engine + security + workers | `cd apps/api && pytest -q` | **50 passed** (SQLite) |
| Same suite on PostgreSQL 16.2 (pip-bundled `pgserver`) | `KIFARU_TEST_DATABASE_URL=postgresql+psycopg://… pytest -q` | **50 passed** |
| WIM signal pipeline | `cd packages/wim_dsp && pytest -q` | **24 passed** |
| AI agents + orchestrator | `cd packages/ai_agents && pytest -q` | **8 passed** |
| SimPy station simulation | `cd packages/simulation && pytest -q` | **15 passed** |
| Lint (ruff, repo config) | `ruff check apps/api packages` | **All checks passed** |

What the suites cover (see the test files for exact assertions):

- Clearance engine: GREEN/AMBER/RED rules, uncertainty margins, every blocking quality flag prevents GREEN, expired
  calibration, identity conflict (cloned tag) → RED, watch-list → RED, seal breach → RED, declaration mismatch
  AMBER/RED, axle-config mismatch, seeded random audit, deterministic evidence hash.
- WIM DSP: axle count, speed (±2 %), spacing/grouping, GVM error < 5 % on a fixed truck and < 6 % on 20 random trucks
  (synthetic signals), temperature compensation reduces bias, dead/noisy sensors flagged.
- API: register/login/refresh rotation/lockout/MFA gating, RBAC matrix, tenant isolation (fleet, events, shipments,
  appointments, WebSocket incl. clearance events), simulate → decision → prescreen ticket → public QR verify → ledger
  chain verify, forced overload → RED → static verification → certified ticket → MFA-gated override, edge ingest
  idempotency, slot capacity/alignment/duplicate rejection, backhaul two-party acceptance, environment labels,
  integrations mock-only, admin users/audit/incidents/agents, station failure → incident → close restores status,
  worker handlers (live ingest, dead-letter, health, periodic jobs).
- Migrations: Alembic `0001` upgrade and downgrade verified on SQLite and PostgreSQL (3 schemas, 38 tables).

## 2. Load test (local, in-process API, SQLite, 16 concurrent clients, 30 s)

`python apps/api/tests/load/load_test.py --inprocess --clients 16 --seconds 30`

| Metric | Run 1 | Run 2 (machine shared with 6 build agents) |
|---|---|---|
| Throughput | 7.5 req/s | 5.0 req/s |
| Errors | 0 | 0 |
| Simulate (full pipeline: 8 kHz synthetic signals → DSP → identity → decision → ticket → ledger) p50 / p95 | 1.46 s / 3.08 s | 3.35 s / 5.10 s |
| List 50 events p50 / p95 | 2.98 s / 5.12 s | 1.36 s / 4.16 s |
| Station overview p50 / p95 | 1.76 s / 3.05 s | 3.31 s / 4.43 s |
| Public ticket verify p50 / p95 | 0.13 s / 0.51 s | 0.26 s / 0.46 s |
| Engine decision latency (`latency_ms`, inside the pass pipeline) mean / p95 / max | 460 / 1225 / 2153 ms | 648 / 2684 / 3104 ms |

Interpretation: these numbers are dominated by SQLite single-writer locking and the Python GIL under 16 threads on a
busy laptop; the simulate path also synthesises and filters ~60 000 samples per pass, which a real lane does on the
STM32 and never in the API. The ≤ 2 s decision-latency target applies at the edge gateway (decision made locally before
any cloud round-trip) and must be measured there in Phase 6/7. A PostgreSQL + multi-worker deployment benchmark is
pending the cloud environment.

## 3. Simulation (modelled, synthetic arrivals)

`packages/simulation/reports/example-report.md` — 11 scenarios, 12 h, 5 replications. Headline (modelled): rolling
clearance reduces the share of trucks stopping at the static scale from 100 % to ≈ 22 % and mean time in system from
≈ 47 min to ≈ 2–3 min at 60 trucks/h with 5 static bays. These are model outputs with synthetic inputs, not measurements.

## 4. Not verified here (and why)

| Item | Reason | Where it is verified |
|---|---|---|
| Cloud deployment, RDS, IoT Core, CloudFront | No AWS account/credentials supplied | `docs/06-operations/deployment-guide.md` (owner steps) |
| Docker images / Compose stack | Docker not installed on this machine | CI workflow builds images |
| STM32 / ESP32 firmware compilation | No ARM/ESP toolchains installed | `firmware/*/README.md` build instructions |
| Flutter app build | No Flutter/Android SDK installed | `apps/mobile/README.md` |
| WIM accuracy on real sensors | No hardware yet | Phase 6 lab rig, Phase 7 shadow mode (`pilot-shadow-mode.md`) |
| Legal axle/GVM limit values | Require confirmation against the current EAC VLC Act schedule | `apps/api/kifaru/services/limits.py` |
