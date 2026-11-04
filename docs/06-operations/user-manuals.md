# KIFARU PORTOS — Web user manuals (per role)

Web app: `apps/web` (React 18 + TypeScript + Vite). Sign in at `/login` with your platform account. After sign-in you land on the
dashboard for your primary role; the top navigation lists every screen your roles allow. The bell icon shows your notification
inbox (tap an item to mark it read). All times are shown in Africa/Nairobi. Every weighing record carries a **source badge**:
`LIVE` means a station gateway measured it; `SIMULATED` means the platform simulator produced it. Simulated data is never
presented as live. A pre-screen (WIM) ticket is informational — only a **static_certified** ticket is a legal weight certificate.

| Route | Roles | Purpose |
|---|---|---|
| `/control` | port_controller, auditor, regulator_readonly (read), platform_admin | Network view |
| `/operator` | weighbridge_operator, platform_admin | Lane console |
| `/transporter` | transporter_admin, dispatcher, platform_admin | Fleet, bookings, backhaul |
| `/driver` | driver, platform_admin | In-cab screen |
| `/owner` | cargo_owner, platform_admin | Cargo passport, alerts, offers |
| `/warehouse` | warehouse_manager, platform_admin | Incoming cargo, readiness |
| `/twin` | port_controller, weighbridge_operator, auditor, regulator_readonly, transporter_admin, dispatcher, platform_admin | 3D twin |
| `/admin` | platform_admin | Administration |
| `/verify/:token` | public (no sign-in) | Ticket verification |

## Port Control Centre (`/control`)
1. Station cards show status, observed queue length, average wait, utilisation and the GREEN/AMBER/RED split of the last hour; port controllers can set a station operational/degraded/offline (offline/degraded opens an incident automatically).
2. The live clearance feed lists `clearance.decided` events as they arrive over the WebSocket, with plate, GVM, latency, rules fired and the source badge.
3. The map (OpenStreetMap tiles) shows every station (colour = status, label = queue) and the last reported position of every vehicle; click a marker for details.
4. Queue forecast: pick a station to see observed queue history and the +15/+30/+60/+120 min forecast with its uncertainty band and model version (`persistence`, `mmc-fallback`, …).
5. Weighing statistics: totals, GREEN rate, stops avoided, mean decision latency and the decision-mix chart, plus the by-source breakdown.
6. Incidents: open incidents across the network with one-click close (port controller), an "Open incident" form, and a toggle to list closed incidents.
7. Environmental summary is labelled **MODELLED**: fuel, CO₂ and cost avoided versus the all-stop baseline, with inputs and assumptions expandable.

## Weighbridge Operator (`/operator`)
1. Choose the station and lane at the top; the header shows station/lane status and the lane calibration validity.
2. "Simulate pass" (POST /weighing/simulate) runs synthetic trucks through the full pipeline: set count, overload / sensor-fault / ANPR-misread / RFID-missing / clone / unregistered probabilities, pavement temperature, an optional specific vehicle, forced GVM and seed. Output is tagged SIMULATED.
3. "Latest pass" shows GVM ± U, axle count/class, speed, plate; tabs give the axle table (load ± U, group, spacing), the decision (badge, instruction, rules fired with severity, group margins vs limits, evidence hash), identity fusion (method, confidence, ANPR/RFID), and the ticket (QR, legal status, signature validity).
4. Static verify / override: record the static-scale GVM for an AMBER/RED pass — this issues the legal `static_certified` ticket and logs the WIM error. The override (release despite the decision) needs an MFA-verified session and an existing static verification; a confirmation dialog precedes it.
5. Lane sensors: click a sensor to set its health (ok/degraded/fault with reason). Load sensors (piezo, bending plate, strain gauge) show their calibration state and an "Add calibration" form; existing calibration records are listed.
6. Lane history lists the latest passes; click a row to inspect it. Verification history lists passes with static records or overrides.
7. New passes on the selected station appear automatically (WebSocket) and are selected.

## Transporter (`/transporter`)
1. Fleet & map: table of your vehicles (axle config, class, tare, max GVM, payload, RFID tags, last seen, watch-list flag) and a map of their last positions with the stations. "Add vehicle" registers a truck (plate, axle config, body type, masses, fleet, RFID EPC); validation errors from the API appear under the fields, duplicates return a 409 message.
2. Shipments: passports where your organisation is the transporter, with the stage timeline and linked weighings.
3. Tickets & clearance: weighing history for your vehicles (source badge on every row); click a pass to see the decision details and its ticket QR.
4. Slot booking: pick station, vehicle, optional shipment and priority, then a free 15-minute window; a full window or a vehicle that already has a booking returns 409 and the message is shown. "My appointments" lets you mark arrived/completed/cancelled.
5. Backhaul: open return-load offers; "Run matching agent" proposes trucks; accept or reject proposals for your trucks (assignment needs both the transporter and the cargo owner to accept); mark delivered.
6. Fuel & cost: revenue, fuel cost, extra km and CO₂ from your backhaul matches, plus a **modelled** what-if (POST /environment/what-if) built from your GREEN/AMBER/RED history and an empty-km slider.

## Driver (`/driver`)
1. First launch: tap your truck once (remembered on the device). The screen then needs no interaction while driving.
2. The large top panel is the latest clearance for your plate: GREEN (proceed), AMBER (divert to static scale) or RED (divert to inspection), with the instruction, time, GVM and source badge. New decisions arrive over the WebSocket and are spoken aloud (toggle "Voice on/off").
3. Tiles show your booked appointment (station, slot time, status) and the queue at that station (trucks waiting, estimated wait, station status, whether an alternate route is allowed).
4. The shipment tile shows the active shipment assigned to the truck, its stage, seal state and outstanding items.
5. On load the app sends one GPS fix to the platform (POST /fleet/vehicles/{id}/position); the status line reports whether it was sent.
6. Everything refreshes automatically (20–60 s polling plus live events). Install the app from the browser menu for a full-screen cab display.

## Cargo Owner (`/owner`, mobile-first)
1. Shipments: list of your passports with stage progress and outstanding items; tap one to open the full passport (stage timeline, outstanding list, predicted release P10/P50/P90 when computed, owner/transporter/truck, containers, seals, processing events, weighings with source badges, tickets with QR and legal status).
2. Register: create a shipment — description, cargo type, origin/destination, declared mass, VGM, KRA declaration reference (moves the shipment to "declared"), seal ID, transporter and destination warehouse, and containers. Container numbers are checked against ISO 6346 as you type and again by the server (422 messages appear under the field).
3. Alerts: your notification inbox (stage changes, delays, backhaul news) with mark-read.
4. Backhaul: publish a return-load offer (route coordinates, window, price), run matching, and accept/reject proposed trucks; assignment requires the transporter to accept too.
5. Works at 360 px and can be installed as a PWA; the shell is cached for low bandwidth, data is always fetched live.

## Warehouse (`/warehouse`)
1. Select your warehouse (if more than one). The card shows dock count, incoming shipment count and readiness; set readiness to ready/busy/closed.
2. Arrival predictions: for every active incoming shipment, the predicted release window (P10/P50/P90, when the prediction has been computed) and any visible weighbridge slot booked for its truck.
3. Incoming shipments table: reference, cargo, truck, stage with timeline, declared mass, predicted release, outstanding items; "Open" shows the full passport.
4. Cargo status: confirm delivery (when released/in transit), close a delivered shipment, or flag the current stage as blocked. Every action is written to the passport and ledger.
5. Live updates on cargo status changes and deliveries.

## Admin (`/admin`)
1. Users: list with roles, MFA state and activity toggle; create users (email, name, password, phone, organisation, roles); edit roles.
2. Stations & lanes: every station with its lanes, device IDs, calibration validity and sensor counts; create stations and lanes (WIM lanes receive the default 13-sensor set).
3. Calibration: summary of load sensors with valid/expired/missing calibration and the record history per sensor.
4. Integrations: the adapter registry with contract, mode (mock/real), base URL, health; switching to real requires a base URL and is confirmed; health check per adapter.
5. Incidents (open/closed, close, open new), Audit log (filter by entity), Ledger tail with **Verify chain** (hash + signature check, head hash, signer key).
6. System health (database, Redis/MQTT configuration, weighings in the last hour, WebSocket subscribers) and the AI agent catalogue (agents, inputs/outputs, pipelines, advisory policy).

## Digital twin (`/twin`)
1. Banner states the data source: **LIVE** only when an event with `source=live` has been received; otherwise **SIMULATION MODE — data is simulated**.
2. The 3D scene shows the container terminal and gate, the trunk road, the first two stations (WIM lane with gantry and static scale), the inspection/holding area and a warehouse. Trucks spawn on `truck.detected`, take the decision colour on `clearance.decided`, continue (GREEN), divert to the static scale (AMBER) or to holding (RED). Ghost trucks show the observed queue length; cones mark open incidents.
3. Scenario comparison (controller/operator): runs the simulator for baseline and +20/30/50 % arrivals and tabulates decision mix, GREEN rate, mean latency, assumed wait and modelled fuel/CO₂ (what-if agent). All rows are SIMULATED.

## Public ticket verification (`/verify/:token`)
Scan a ticket QR or paste the token/link. The page shows whether the signature is valid and, prominently, the legal status
(**LEGAL WEIGHT CERTIFICATE** for static-scale tickets, **PRE-SCREEN ONLY** otherwise), plus plate, GVM, station, time, decision,
source and evidence hash. No sign-in is needed and no sensitive fields are returned.
