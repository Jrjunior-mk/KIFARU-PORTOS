# KIFARU PORTOS — Technology Stack and Justification

| Layer | Choice | Why this, not the alternative |
|---|---|---|
| Backend language | **Python 3.12** | Same language for API, DSP (NumPy/SciPy), ML and simulation (SimPy) — one team, one toolchain. Go/Node would split the ML and DSP work into a second stack. |
| API framework | **FastAPI + Pydantic v2** | Async, typed request/response validation (security requirement), OpenAPI generated for free (API documentation deliverable). Django REST is heavier and sync-first; Flask lacks typed validation. |
| ORM / migrations | **SQLAlchemy 2.0 + Alembic** | Mature, explicit, supports both PostgreSQL in prod and SQLite for fast local tests. |
| Relational DB | **PostgreSQL 16** (RDS) | JSONB for evidence, exclusion constraints for slot booking, partitioning for time-series, row-level security possible. |
| Time-series | **Native partitioning + pg_partman** (TimescaleDB optional self-hosted) | RDS does not ship TimescaleDB; raw 8 kHz data stays at the edge/S3 anyway, cloud only stores decimated stats. |
| Cache / realtime state | **Redis 7** (ElastiCache) | Pub/sub for WS fan-out, rate limiting, queue state, idempotency keys. |
| Messaging (edge) | **MQTT 5 over TLS, mTLS** (AWS IoT Core; EMQX locally) | Store-and-forward friendly, QoS 1, tiny over LTE. |
| Jobs | **SQS + worker** (local: Redis streams) | Managed, dead-letter queues, no broker to run. |
| Auth | **Argon2id, JWT (15 min) + rotating refresh, TOTP MFA** | Portable (not locked to Cognito), meets MFA-for-privileged requirement. |
| Signing | **Ed25519** (PyNaCl) | Fast, small signatures for tickets/ledger; verifiable in browser (tweetnacl). |
| Frontend | **React 18 + TypeScript + Vite** | Fast builds, SPA on S3/CloudFront; Next.js SSR not needed for authenticated dashboards and complicates static hosting. |
| Styling | **Tailwind CSS** | Rapid, consistent role dashboards. |
| Charts | **Recharts** | Simple, SVG, works with the dataviz design rules. |
| Maps | **MapLibre GL + OpenStreetMap tiles** | Open, no per-load fee; satellite/road tiles swappable. |
| 3D twin | **Three.js** (via `@react-three/fiber`) | Required by brief; declarative scene tied to React state. |
| Mobile | **Flutter** (Phase 3) with a PWA interim | Single codebase Android/iOS, good offline story; PWA gives low-bandwidth cargo owners access without an install. |
| ML | **scikit-learn, XGBoost** (tabular forecasts), **PyTorch** only where a sequence model proves better in backtests | Start with explainable gradient boosting; deep models must earn their place. |
| CV / OCR | **YOLOv8 (plate detection) + PaddleOCR (plate text)** on the edge gateway | Proven open stack; runs on CPU/iGPU at lane frame rates. |
| DSP | **NumPy/SciPy** (python reference) → **CMSIS-DSP** (firmware port) | Same algorithm validated in Python before porting to STM32. |
| Firmware | **STM32H743, C, FreeRTOS, STM32Cube HAL** | DMA-driven SPI from ADS131M08, CAN-FD/Ethernet uplink. |
| Aux nodes | **ESP32-S3, ESP-IDF** | Cheap environmental/cabinet monitoring over CAN/Wi-Fi. |
| Simulation | **SimPy** (queues, Python-native, testable in CI); **SUMO** adapter for road-network traffic; **LTspice/Proteus** for analog | SimPy runs in CI; SUMO is optional heavy tooling. |
| IaC | **Terraform (AWS provider)** | Multi-env workspaces, reviewable plans. |
| CI/CD | **GitHub Actions** | OIDC to AWS, no long-lived keys. |
| Containers | **Docker, Compose** (local) / **ECS Fargate** (cloud) | Same image everywhere. |
| Observability | **CloudWatch + structured JSON logs (structlog) + Sentry (optional)** | Managed; cost-effective at this scale. |
