# KIFARU PORTOS — Implementation Roadmap

| Phase | Scope | Depends on | Milestone / acceptance criteria | Target |
|---|---|---|---|---|
| **1 Architecture & design** | Source review, RTM, system/cloud/DB/hardware architecture, stack, roadmap | — | All docs in `docs/01-requirements`, `docs/02-architecture` reviewed by owner; open questions in `00-source-review.md` answered | 2026-11 |
| **2 Core working platform** | Auth+RBAC, orgs/fleets/vehicles, stations/lanes/sensors, WIM simulator, identity simulator, **clearance engine**, tickets+QR, shipments/passport, ledger, Postgres+Alembic, Docker Compose, Terraform (validated), CI | 1 | `pytest` green incl. clearance rule tests; `docker compose up` gives working API+web; `terraform validate` passes; live deploy **only** when AWS access granted | 2026-11/12 |
| **3 Logistics intelligence** | Queue records, appointments/slots, truck & cargo tracking (telematics adapter), notifications (WS/SMS/email), transporter + cargo-owner + driver UIs, PWA | 2 | Slot booking rejects over-capacity; dashboards update over WS without refresh; SMS adapter sends via Africa's Talking sandbox | 2027-01 |
| **4 Advanced AI** | Queue forecasting (15/30/60/120), backhaul matching + marketplace flow, cargo anomaly detection, release prediction, environmental model, agent orchestrator | 3 | Backtest report for forecaster; matcher unit tests; no automatic commercial assignment; emissions formulas documented | 2027-02 |
| **5 Digital twin & integrations** | Three.js port, SimPy/SUMO scenarios + comparison reports, adapters (mock → real where authorised) | 3, 4 | Twin shows live events with simulation banner when not live; scenario CLI produces comparison table; adapter health page | 2027-03 |
| **6 Industrial prototype** | STM32 DAQ firmware, AFE boards, lab rig, calibration, edge gateway, hardware→cloud | 2 | Bench: axle pulses captured at 8 kSPS; lab-rig load error vs reference reported with uncertainty; outage store-and-forward test passes | 2027-04/05 |
| **7 Pilot readiness** | Shadow mode at a weighbridge (WIM decisions logged, not enforced), fault injection, security review, accuracy benchmark vs static scale, docs, runbooks | 5, 6 | KPIs reported against MP §12 targets with real data; regulator pack | 2027-06+ |

Critical path: 1 → 2 → 3 → 4 → 5 → 7, with 6 in parallel from Phase 2 onward.
Blocking external dependencies: AWS account (Phase 2 deploy), SMS account (3), weighbridge site access and regulator engagement (6–7).
