# KIFARU PORTOS — Web frontend

React 18 + TypeScript + Vite + Tailwind. Role dashboards, public ticket verification, a Three.js digital twin and an installable
PWA (cargo-owner and driver views). Everything on screen comes from the API in `apps/api`; there is no mock data in the frontend,
and every weighing record shows its `source` badge (`LIVE` only when a station gateway produced it).

## Setup

```bash
# prerequisites: Node >= 20, the API running on http://localhost:8000 (see apps/api)
cd apps/web
npm install
npm run dev            # http://localhost:5173 — /api and /ws are proxied to http://localhost:8000
```

Run the backend first (from `apps/api`): `python -m kifaru.seed` then `python -m uvicorn kifaru.main:app --port 8000`.
Demo accounts: created by `python -m kifaru.seed`, which prints the e-mail addresses and a generated password once (not stored in the repository).
dispatch@transporter-a.invalid, driver1@transporter-a.invalid, owner@cargo-a.invalid, wh@warehouse-a.invalid.

## Scripts

| Script | What it does |
|---|---|
| `npm run dev` | Vite dev server with API/WS proxy |
| `npm run build` | `tsc --noEmit` (strict, zero errors required) then `vite build` into `dist/` with the PWA service worker |
| `npm run preview` | Serve `dist/` locally on :4173 |
| `npm run typecheck` | TypeScript only |
| `npm run smoke [apiBase]` | Headless integration check against a running API: login/refresh for each demo role, operator simulate → ticket → QR → public verify → static verify → override, sensor health, calibration, forecast, cargo-owner shipment creation (valid + ISO 6346 422), backhaul offer + matching, transporter scoping, slot booking + 409, RBAC 403, what-if, ledger verify, agents, integrations, WebSocket hello |

## Environment variables

| Variable | Default | Meaning |
|---|---|---|
| `VITE_API_BASE` | `` (same origin) | API origin without trailing slash, e.g. `https://api.kifaru.example`. Empty = use `/api` on the page origin (dev proxy or nginx). |
| `VITE_WS_BASE` | derived | Explicit WebSocket origin (`wss://…`). Derived from `VITE_API_BASE` or the page origin when empty. |

Copy `.env.example` to `.env` for local overrides. Variables are baked in at build time.

## Route → role map

`platform_admin` can open every route. Roles come from the JWT / `GET /auth/me`; the nav only shows allowed screens and routes
render an "Access restricted" card otherwise.

| Route | Roles |
|---|---|
| `/login` | public |
| `/verify/:qrToken`, `/verify` | public (GET /api/v1/tickets/verify/{token}) |
| `/control` | port_controller, auditor, regulator_readonly |
| `/operator` | weighbridge_operator |
| `/transporter` | transporter_admin, dispatcher |
| `/driver` | driver |
| `/owner` | cargo_owner |
| `/warehouse` | warehouse_manager |
| `/twin` | port_controller, weighbridge_operator, auditor, regulator_readonly, transporter_admin, dispatcher |
| `/admin` | platform_admin |

## Architecture notes

- `src/api/types.ts` — hand-written types mirroring every router in `apps/api/kifaru/routers`. `src/api/endpoints.ts` — one typed function per operation. `src/api/client.ts` — fetch wrapper: bearer auth, one silent refresh + retry on 401 (rotating refresh tokens), `ApiError` with `fieldErrors` for pydantic 422 detail.
- `src/auth` — token store (sessionStorage, or localStorage when "remember this device" is ticked for installed PWAs), `AuthProvider` with proactive refresh ~60 s before expiry, MFA step when `mfa_required`, logout revokes the refresh session.
- `src/hooks/useLiveEvents.ts` — `useLiveEvents(types?, station?)` over `/ws/events` with exponential back-off reconnect, `hello.recent` replay, ping handling and `hasLive` (true once any event carries `source === "live"`).
- Lazy routes: all dashboards are code-split; MapLibre (`StationMap`) and Three.js (`twin/Scene`) load only when their screens open. The service worker precaches the shell only (~370 KB); map/3D/chart chunks are cached on first use. API/WS responses are never cached.
- Design: slate/teal palette, amber/green/red strictly for clearance decisions; chart series colours were validated for colour-vision deficiency in light and dark mode; dark mode follows `prefers-color-scheme`.

## Docker

```bash
docker build -t kifaru-web apps/web
docker run -p 8080:80 -e API_UPSTREAM=http://host.docker.internal:8000 kifaru-web
```

nginx serves `dist/` with SPA fallback and proxies `/api/`, `/ws/`, `/docs`, `/openapi.json` to `$API_UPSTREAM` (templated at
container start from `nginx/nginx.conf.template`). `/healthz` returns `ok`.

## Known API gaps (frontend works around or surfaces them)

- `POST /stations/sensors/{id}/calibrations` returns 500 when the sensor already has a calibration record (naive vs aware datetime
  comparison on SQLite). The UI shows the server error; the first calibration per sensor works.
- No driver → vehicle assignment endpoint: the driver screen asks the driver to pick a truck once (stored on the device).
- `GET /queue/appointments/mine` is scoped to the caller's org via vehicle ownership, so warehouse managers cannot see
  appointments for incoming trucks owned by transporters; the arrival table shows "none visible" in that case.
- `predicted_release_*` fields exist on the passport but no endpoint triggers the release-prediction agent; the UI shows the
  window only when present.
- Notifications are only created by `POST /notifications/send` (controller/dispatcher); stage changes do not auto-notify owners.
- Incidents live under `/admin/incidents` but are readable by any authenticated user and writable by controllers/operators —
  the control centre relies on that.

## User manual (per role)

See `docs/06-operations/user-manuals.md` (same content, kept in sync).

### Port Control Centre (`/control`)
Station cards (status, queue, wait, utilisation, last-hour decision mix, status actions), live clearance feed over WebSocket, OSM
map of stations and vehicle positions, queue forecast (+15/30/60/120 min with band and model version), weighing statistics,
incidents (open/close/create, closed list) and the **modelled** environmental summary.

### Weighbridge Operator (`/operator`)
Station/lane selector; "Simulate pass" with all simulator options; latest-pass tabs: axle readings (load ± U, group, spacing),
decision (badge, instruction, rules fired, margins, evidence hash), identity (method, confidence, ANPR/RFID), static verify and
MFA-gated override, ticket QR with legal status; lane sensor health grid with POST health; per-load-sensor calibration list and
"Add calibration" form; lane history and verification history.

### Transporter (`/transporter`)
Fleet table + add-vehicle form, vehicle map, shipments with stage timelines, weighing tickets and clearance history, 15-minute slot
booking with 409 handling and appointment status updates, backhaul opportunities with matching and transporter accept/reject/deliver,
fuel & cost analytics from matches plus a modelled what-if.

### Driver (`/driver`)
Pick truck once; then a no-touch screen: huge GREEN/AMBER/RED panel with diversion instruction (spoken via Web Speech API when new),
appointment tile, queue tile, shipment tile; one GPS fix sent on load; polling + live events.

### Cargo Owner (`/owner`)
Mobile-first list → passport (stages, outstanding, P10/P50/P90 when present, containers, seals, weighings, tickets with QR); register
shipment with live ISO 6346 feedback and server 422 mapping; alerts inbox; backhaul offers with matching and owner accept/reject.

### Warehouse (`/warehouse`)
Warehouse card with readiness toggle, arrival predictions (predicted release + visible slots), incoming shipments table, passport
view with delivery/close/blocked actions.

### Admin (`/admin`)
Users (create, roles, active), stations/lanes/sensors (create station, create lane), calibration records, integrations (mock/real,
health), incidents, audit log, ledger tail + verify chain, system health, AI agent catalogue.

### Digital twin (`/twin`)
LIVE / SIMULATION MODE banner, 3D port + two stations scene with event-driven trucks coloured by decision, queue ghosts, incident
markers, and the scenario panel (baseline, +20/30/50 %) with decision mix, latency and modelled fuel.

### Public verification (`/verify/:token`)
Signature validity and legal status (certificate vs pre-screen) shown prominently, plus plate, GVM, station, time, source.
