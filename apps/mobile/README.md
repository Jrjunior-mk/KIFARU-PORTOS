# KIFARU PORTOS - Driver and Cargo-Owner Mobile App (Flutter)

Flutter 3.x / Dart 3 (null-safe) client for the KIFARU PORTOS smart-port
weigh-in-motion rolling-clearance platform. Two audiences, one codebase:

* **Drivers** - a hands-free *Driver Mode* that shows and speaks the latest
  GREEN / AMBER / RED clearance, the booked slot and the live queue.
* **Cargo owners** - shipment registration, the Digital Cargo Passport, signed
  ticket QR codes, release predictions and a notification inbox.

> **Build status: NOT COMPILED HERE.** This project was authored on a Windows 11
> machine without the Flutter or Android SDKs installed, so `flutter build`,
> `flutter analyze` and `flutter test` have **not** been run. The code targets
> stable Flutter >= 3.19 / Dart >= 3.3 and only uses mainstream, pinned
> packages, but expect to fix minor analyzer findings on first build.
> See "What has not been verified" at the end.

---

## 1. Setup

Prerequisites: Flutter stable (>= 3.19), Android SDK (API 21+) and/or Xcode 15+.

```bash
cd apps/mobile

# 1. Generate the platform scaffolding that is intentionally not committed
#    (Gradle files, MainActivity, Runner.xcodeproj, icons, ...).
#    Existing files - pubspec.yaml, lib/, test/, AndroidManifest.xml,
#    Info.plist - are NOT overwritten by `flutter create .`.
flutter create . --org ke.kifaru --project-name kifaru_mobile --platforms android,ios

# 2. Dependencies
flutter pub get

# 3. Static checks and unit tests
flutter analyze
flutter test

# 4. Run (Android emulator: the API default is http://10.0.2.2:8000 = host loopback)
flutter run
```

After `flutter create .` set `minSdkVersion 21` (or higher) in
`android/app/build.gradle` if the template sets a lower value; geolocator and
flutter_secure_storage need 21+ (secure storage prefers 23+).

### Dependencies (pubspec.yaml)

| Package | Why |
|---|---|
| `http` | REST calls |
| `flutter_secure_storage` | access / refresh JWT in the platform keystore |
| `web_socket_channel` | `/ws/events` live feed |
| `geolocator` | GPS position every 60 s in Driver Mode |
| `flutter_tts` | spoken decisions (English + Kiswahili) |
| `provider` | state management (ChangeNotifier) |
| `qr_flutter` | QR of the public ticket verify URL |
| `intl` | date / number formatting |
| `shared_preferences` | settings + offline cache + GPS outbox |
| `wakelock_plus` | keep the Driver Mode screen on |

---

## 2. Configuration

All configuration is in-app (Settings screen) and persisted:

| Setting | Default | Notes |
|---|---|---|
| API base URL | `http://10.0.2.2:8000` | Android-emulator loopback. Use the LAN IP / HTTPS host for devices. The app appends `/api/v1`. Changing it signs you out. |
| Public verify base URL | `http://localhost:5173` | Mirrors the API's `public_base_url`; QR codes encode `<base>/verify/<qr_token>`. The API does not expose this value, so it is a setting (see API gaps). |
| Language | `en` | `en` / `sw`. All UI strings come from `lib/l10n/strings.dart`. |
| Low-bandwidth mode | off | Text only (no QR images, no prediction explanation), polling 90 s (driver) / 5 min (cargo) instead of 30 s / 60 s. |
| Spoken announcements | Kiswahili + English | or one language only. |

Android `usesCleartextTraffic="true"` and the iOS `NSAllowsLocalNetworking`
entry exist for local development; remove them for production builds.

---

## 3. Project structure

```
lib/
  main.dart                      bootstrap (prefs, API client, auth) -> runApp
  app.dart                       providers, theme, root gate (loading / login / home)
  core/
    api_client.dart              base URL, bearer auth, single-flight refresh on 401, typed errors
    api_exceptions.dart          Unauthorized/Forbidden/NotFound/Conflict/Validation(422 field errors)/Locked/Network
    ws_client.dart               reconnecting WebSocket (back-off 1-30 s, hello/ping handling)
    cache.dart                   JSON cache with stored-at timestamp ("last updated" age)
    offline_queue.dart           GPS store-and-forward queue (flushes oldest-first)
    iso6346.dart                 container number check digit (mirrors the API)
    decision_instruction.dart    GREEN/AMBER/RED -> instruction key (+ static lane), plate normaliser
    json_utils.dart, format.dart helpers (UTC parsing, local display)
  models/                        Token, Me, Vehicle, Station(+Lane, Slot), Appointment,
                                 WeighingEvent(+Decision, Axle, Identity), ShipmentPassport
                                 (+PassportWeighing, PassportTicket, ProcessingEvent),
                                 AppNotification, TicketVerification - all with fromJson
  state/
    app_settings.dart            persisted settings (ChangeNotifier)
    auth_state.dart              login / refresh / logout / me (secure storage + cached Me)
    driver_state.dart            appointment + station queue + latest decision; WS + polling;
                                 TTS; GPS every 60 s with offline queue; cache
    cargo_state.dart             shipments + inbox; WS + polling; cache; register; mark read
  l10n/strings.dart              en + sw maps, placeholders, decision/stage/source labels
  screens/                       see section 4
  widgets/                       SourceBadge (LIVE / SIMULATED / REPLAY), LastUpdatedLabel, ErrorBanner
test/
  iso6346_test.dart              check-digit algorithm, normalisation, error keys
  decision_instruction_test.dart decision -> instruction mapping in en + sw, plate normaliser
android/app/src/main/AndroidManifest.xml   INTERNET, ACCESS_FINE/COARSE_LOCATION, WAKE_LOCK
ios/Runner/Info.plist                      NSLocationWhenInUseUsageDescription, local networking
```

---

## 4. Screens and the API calls behind them

Every value on screen comes from the API. There is no demo or seeded data in
the app; empty states are shown when the API returns nothing.

| Screen | Role | API |
|---|---|---|
| **Login** | all | `POST /auth/login {email,password,totp_code?}` -> tokens stored in secure storage; `GET /auth/me`. TOTP field is optional and appears on demand. `POST /auth/refresh` is called automatically on 401 (rotating refresh token); `POST /auth/logout` on sign-out. |
| **Home gate** | all | Routes by `roles`: `driver` / `transporter_admin` / `dispatcher` -> vehicle selection; `cargo_owner` -> cargo tabs; both -> chooser; others -> unsupported notice. |
| **Vehicle selection** | driver | `GET /fleet/vehicles` (org-scoped). Requests location permission, then opens Driver Mode. Remembers the last vehicle. |
| **Book slot** | driver | `GET /stations`, `GET /queue/{station}/slots`, `POST /queue/{station}/appointments {vehicle_id, slot_start}`. 409 (slot full / already booked) is shown as returned. |
| **Driver Mode** | driver | `GET /queue/appointments/mine` (filtered to the vehicle, active statuses), `GET /stations/{id}` (queue length, avg wait, status, static lane number), `GET /weighing/events?vehicle_id=&limit=1` (latest decision, ticket type, source). WebSocket `ws://host/ws/events?token=JWT&types=clearance.decided,queue.updated`; polling fallback every 30 s (90 s low-bandwidth). `POST /fleet/vehicles/{id}/position {lat,lon}` every 60 s, queued in shared_preferences when offline and flushed later. |
| **Shipments** | cargo owner | `GET /shipments` (cached, pull-to-refresh, WS `cargo.*` / `shipment.delivered` triggers reload). |
| **Register shipment** | cargo owner | `POST /shipments` with description, cargo type, origin, destination, declared mass, optional ISO 6346 container (validated client-side, 40 ft GP), declaration reference, seal id. 422 field errors are mapped onto the form. |
| **Cargo passport** | cargo owner | `GET /shipments/{id}`: stage timeline (10 stages), outstanding list, weighings with **source badge**, tickets with QR (`qr_flutter`) encoding `<public base>/verify/<qr_token>` (text link in low-bandwidth mode), predicted release P10 / P50 / P90 (`predicted_release_p10`, `predicted_release_at`, `predicted_release_p90`), containers, seals, processing history. |
| **Inbox** | cargo owner | `GET /notifications`, `POST /notifications/{id}/read` (optimistic). WS `notification` events reload. |
| **Verify ticket** | all (public) | `GET /tickets/verify/{qr_token}` without auth. Accepts a raw token or a pasted verify URL. Shows validity, legal status, plate, GVM, decision, station, source, evidence hash. |
| **Settings** | all | API URL, public verify URL, language, low-bandwidth, TTS language. |

### Driver Mode behaviour in detail

* Black background, white / high-contrast text; decision word at 110 pt inside a
  full-colour panel (GREEN `#00C853` / AMBER `#FFC400` / RED `#D50000`), the
  instruction at 40 pt: **Continue** / **Proceed to static scale - lane N** /
  **Stop for inspection** (N = the station's `static` lane from `GET /stations/{id}`;
  without one the lane-less text is used).
* Appointment block: station code, slot window, live countdown ("Slot in 12 min",
  "Slot is open now", "Slot passed 5 min ago").
* Queue block: trucks waiting, average wait, station status.
* Top bar: plate, live / reconnecting / offline indicator, "Updated x ago", GPS
  status (sent / queued (n) / denied).
* Every weighing shows its `source` badge (LIVE / SIMULATED / REPLAY) and the
  pre-screen disclaimer ("not a legal weight certificate").
* New decisions are spoken with `flutter_tts` - Kiswahili then English by
  default (`sw-KE`, `en-GB`), configurable. Cached decisions are never
  re-announced; stale decisions (> 30 min) are shown but not spoken unless they
  arrive by WebSocket.
* Screen stays on (`wakelock_plus`), system bars hidden, back button disabled.
* **The only control is a long press (hold ~2 s anywhere) to exit.**

### Why the driver must never touch the phone

Kenyan traffic law (Traffic Act Cap. 403, s. 53A / Rule 93 of the Traffic Rules)
prohibits handling a mobile phone while driving, and the WIM lane is precisely
where a 56-tonne truck is being measured at speed. The platform's own
architecture states the lane instruction is delivered by the roadside
signal/VMS within ~1.3 s; the phone is a secondary channel. Therefore the app:

1. requires all choices (vehicle, slot, settings) **before** entering Driver Mode;
2. presents one glanceable panel sized for a dashboard mount - colour first,
   then one word, then one sentence;
3. speaks every new decision in the driver's language so no glance is required;
4. refreshes itself (WebSocket push + polling + GPS) with no user action;
5. exposes no tap targets - an accidental tap can do nothing, and exiting
   requires a deliberate 2-second hold.

### Offline tolerance

* Last appointment / station / decision (per vehicle), vehicle list, shipments
  and inbox are cached in shared_preferences with a stored-at timestamp; the UI
  shows "Updated x ago" and an orange *Offline - showing cached data* marker.
* GPS samples that cannot be posted are queued (max 120) and flushed
  oldest-first on the next successful request.
* The `Me` profile is cached so the app opens to the right role without network.
* Low-bandwidth mode halves background traffic and drops images.

---

## 5. Test plan

### Unit tests (present, run with `flutter test`)

* `test/iso6346_test.dart` - check digit for known numbers, normalisation,
  wrong-digit and format errors, letter-value table (multiples of 11 skipped),
  remainder-10 -> digit 0 rule.
* `test/decision_instruction_test.dart` - GREEN/AMBER(with and without lane)/RED/
  unknown mapping, both languages, no untranslated keys, plate normaliser,
  placeholder substitution and fallbacks.

### Widget tests to write (not yet present)

| Test | What it asserts |
|---|---|
| `driver_mode_panel_test` | Given a `DriverState` with a RED decision, the panel shows "RED", "Stop for inspection", the SIMULATED badge when `source == 'simulated'`, and contains **no** `ButtonStyleButton`/`IconButton` widgets. |
| `driver_mode_exit_test` | A `longPress` shorter than 1.5 s does not pop; a hold >= 1.5 s pops the route. |
| `driver_mode_countdown_test` | With `slot_start` 10 min ahead, the appointment block reads "Slot in 10 min" and updates after `tester.pump(Duration(minutes: 1))`. |
| `login_test` | 401 `detail` from a fake `http.Client` is rendered; `mfa_required: true` reveals the TOTP field. |
| `register_shipment_test` | Entering `CSQU3054380` shows the check-digit error and blocks submit; `CSQU3054383` submits a body with `containers[0].number`. 422 from a fake client maps to `declared_mass_kg`. |
| `passport_detail_test` | Stage timeline marks indices <= `stage` as done; each weighing row has a `SourceBadge`; low-bandwidth hides `QrImageView` and shows the URL text. |
| `ticket_verify_test` | Fake 200 `{valid:false}` renders NOT VALID; pasted URL `https://x/verify/abc` requests `/tickets/verify/abc`. |
| `api_client_test` | 401 -> `onRefresh` once -> retry with new token; two concurrent 401s share one refresh; 409/422/403 map to typed exceptions with `detail`. |
| `ws_client_test` | `hello.recent` events are replayed; `ping` ignored; reconnect scheduled on close. |
| `position_queue_test` | Enqueue when offline, cap at 120, flush stops on `NetworkException`, drops on 4xx. |

### Manual / device checks

* TTS voice availability for `sw-KE` on the target Android image (falls back to
  the engine default otherwise).
* Wakelock and immersive mode on a dashboard mount; brightness in sunlight.
* Location permission flows on Android 13+/iOS 17 (while-in-use only).
* WebSocket behaviour across network hand-over (LTE <-> Wi-Fi).

---

## 6. API gaps found while building (report, not changed)

1. **`clearance.decided` payload has no `vehicle_id` or `qr_token`** - only
   `plate`. The driver app matches on the normalised plate and then re-fetches
   `GET /weighing/events?vehicle_id=&limit=1` to get the ticket. Adding
   `vehicle_id`, `decision_id`-linked `qr_token` and `station_code` to the event
   payload would remove one round-trip per decision.
2. **No static-lane number in the decision.** The AMBER instruction "lane N"
   is derived from the station's lanes (`type == 'static'`). The engine/edge
   should emit the assigned lane so the app, VMS and SMS all say the same thing.
3. **`clearance.decided` is published without `org_id`**, so with the
   WebSocket's tenant filter (`org_id in (None, org)`) every driver receives
   every station's decisions and must filter client-side. Tagging the event
   with the vehicle's `org_id` would reduce traffic and leakage of plates.
4. **No "my vehicle" for a driver.** `GET /fleet/vehicles` returns the whole
   organisation; the driver picks manually. A `Driver.user_id` link (or
   `/fleet/drivers/me`) would allow auto-selection.
5. **`public_base_url` is not exposed** by the API, so the QR link base is a
   client setting. A `GET /api/v1/meta` (or including `verify_url` in ticket
   payloads) would avoid mismatches.
6. **No pagination / since-filter on `GET /shipments` and `GET /notifications`**
   (fixed `limit=100` on notifications). Low-bandwidth clients would benefit
   from `?since=` and `?limit=`.
7. **No `DELETE`/cancel for an appointment by the driver** other than
   `POST /appointments/{id}/status {cancelled}`; fine, but the mobile app does
   not expose it in Driver Mode by design.
8. **No unauthenticated clearance-by-plate lookup** for USSD/SMS (see
   `docs/06-operations/ussd-sms-spec.md`).
9. **`GET /notifications/templates/sms` requires auth**; harmless, but a USSD
   gateway would call it with a service token.
10. **Timestamps from the SQLite dev server are naive**; the app treats naive
    ISO strings as UTC (as the API stores UTC). PostgreSQL deployments return
    `+00:00` and are unaffected.

---

## 7. What has not been verified

* Compilation (`flutter analyze`, `flutter build`) - no Flutter SDK available.
* Package API details against the exact pinned versions (e.g. `WebSocketChannel.ready`
  requires web_socket_channel >= 2.4.0; `PopScope` requires Flutter >= 3.16).
* TTS language availability (`sw-KE`) on real devices.
* iOS `Info.plist` merges with the Xcode project generated by `flutter create`.
* End-to-end against a running API with seeded stations / vehicles.
