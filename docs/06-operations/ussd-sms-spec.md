# KIFARU PORTOS - USSD and SMS Channel Specification

Status: design (no backend implementation yet). Companion to the Flutter app in
`apps/mobile`. Audience: backend team, operations, the SMS/USSD aggregator
integration owner.

## 1. Why a USSD/SMS channel

A large share of drivers and small cargo owners on the Northern Corridor use
feature phones or have intermittent data. The architecture (tech-stack.md)
requires "SMS/USSD-compatible notifications" and a low-bandwidth path. USSD is
session-based, works on any GSM handset without data, and is the de-facto
self-service channel in Kenya; SMS carries the asynchronous notifications the
platform already generates (`SMS_TEMPLATES` in
`apps/api/kifaru/routers/notifications.py`).

Safety rule carried over from the mobile app: **a driver never interacts while
moving**. USSD is for the yard, the parking area and the home, not the WIM lane.
The lane instruction is delivered by the roadside signal/VMS and, for smartphone
users, by the spoken Driver Mode. SMS `clearance` messages are a *record*, not a
real-time instruction.

## 2. Service codes (PLACEHOLDERS - not allocated)

| Code | Purpose | Status |
|---|---|---|
| `*384*54327#` | KIFARU self-service USSD (54327 = "KIFAR" on a keypad) | **placeholder**; `*384*` is the shared-code range used by Kenyan aggregators (e.g. Africa's Talking) and a dedicated sub-code must be applied for through the aggregator and the CA |
| `40404` / TBD | SMS short code (two-way: `STOP`, `HELP`, `KIFARU <plate>`) | **placeholder**; requires short-code lease and sender-ID registration |
| Sender ID `KIFARU` | Alphanumeric sender for outbound SMS | to be registered with each MNO via the aggregator |

Nothing in this document reserves or implies ownership of these codes.

## 3. USSD menu tree

Constraints: max 182 characters per screen (we design to <= 160 to be safe),
session timeout 180 s (MNO-dependent), inputs are digits or short text. Language
is chosen once per MSISDN and remembered (default from the user's profile, else
English). Every screen below is given in English; the Kiswahili variants use the
same keys as `apps/mobile/lib/l10n/strings.dart`.

```
*384*54327#
|
+-- (first use) Lugha / Language:  1 Kiswahili  2 English
|
+-- MAIN MENU  "KIFARU PORTOS"
    1 Clearance by plate
    2 Shipment by reference
    3 Book a slot
    4 My appointment
    5 Language / Lugha
    0 Help
```

### 3.1 Clearance by plate (drivers, transporters)

```
1 -> "Enter plate (e.g. KBZ123A):"
   -> lookup latest weighing for the plate (normalised) within the caller's org
      END "KBZ 123A: GREEN at MSA-WIM1 14:32. Continue. Pre-screen only.
           [SIMULATED]"                                  (<= 160 chars)
      END "KBZ 123A: AMBER at MSA-WIM1 14:32. Proceed to static scale lane 9."
      END "KBZ 123A: RED at MSA-WIM1 14:32. Stop for inspection."
      END "No weighing found for KBZ 123A in the last 24 h."
```

Rules:
* The `source` of the weighing is appended in brackets when it is not `live`
  (`[SIMULATED]`, `[REPLAY]`) - same rule as the app's badge.
* The pre-screen disclaimer is always present for `prescreen` tickets; for
  `static_certified` the text reads "Static certified".
* Only plates belonging to the caller's organisation (MSISDN -> user -> org)
  are answered; otherwise "Plate not in your fleet". Platform-wide roles are
  never granted over USSD.

### 3.2 Shipment by reference (cargo owners)

```
2 -> "Enter shipment reference (KP-XXXXXXXX):"
   -> GET /shipments/{reference}  (visibility rules of the API apply)
      CON "KP-1A2B3C4D: At port. 4 steps left. Est. release 16 Nov 10:30
           (P10 09:10 / P90 13:45).
           1 Steps  2 Weighings  3 Back"
         1 -> END "Outstanding: customs, weighing, gate, released, in transit..."
         2 -> END "Last weighing 42.1 t GREEN 15 Nov 14:32 MSA-WIM1 [LIVE]"
```

### 3.3 Book a slot (drivers, dispatchers)

```
3 -> "Enter plate:"
   -> "Station:  1 MSA-WIM1 (queue 12, ~18 min)  2 MSA-WIM2 (queue 4, ~6 min)  3 More"
   -> "Next slots:  1 14:45  2 15:00  3 15:15  4 15:30   (free/cap shown)"
   -> "Confirm KBZ123A at MSA-WIM1 15:00?  1 Yes  2 No"
   -> END "Booked. SMS confirmation follows."   -> SMS template `slot_assigned`
   -> END on 409: "Slot full, choose another."  /  "Vehicle already has a slot."
```

Only 15-minute windows aligned as the API requires are offered (taken straight
from `GET /queue/{station}/slots`).

### 3.4 My appointment

```
4 -> "Enter plate:" -> END "KBZ123A: MSA-WIM1 15:00-15:15, booked. Est. wait 18 min."
                       END "No active appointment for KBZ123A."
```

### 3.5 Language, Help

```
5 -> "1 Kiswahili  2 English"  -> END "Lugha imewekwa: Kiswahili"
0 -> END "KIFARU PORTOS: clearance, shipments, slots. Support 0800 000 000 (placeholder).
          Reply STOP to 40404 to opt out of SMS."
```

### 3.6 Kiswahili screen samples

| Key | Kiswahili |
|---|---|
| Main menu | `KIFARU PORTOS 1 Uamuzi kwa namba ya gari 2 Mzigo kwa nambari 3 Weka nafasi 4 Miadi yangu 5 Lugha 0 Msaada` |
| GREEN | `KBZ 123A: KIJANI MSA-WIM1 14:32. Endelea. Ukaguzi wa awali tu.` |
| AMBER | `KBZ 123A: MANJANO MSA-WIM1 14:32. Nenda kwenye mizani ya kusimama njia 9.` |
| RED | `KBZ 123A: NYEKUNDU MSA-WIM1 14:32. Simama kwa ukaguzi.` |

## 4. SMS templates

### 4.1 Existing templates (verbatim from `SMS_TEMPLATES`, must stay <= 160 chars after substitution)

| Key | Template | Length (template) |
|---|---|---|
| `slot_assigned` | `KIFARU: {plate} slot {slot} at {station}. Est wait {wait} min. Reply STOP to opt out.` | 86 |
| `clearance` | `KIFARU: {plate} {decision} at {station}. {instruction}` | 54 |
| `cargo_stage` | `KIFARU: Shipment {ref} now {stage}. ETA release {eta}.` | 55 |
| `backhaul` | `KIFARU: Return load {title} {origin}->{dest}, KES {price}. Open app to accept.` | 79 |
| `delivered` | `KIFARU: Shipment {ref} delivered. Asante.` | 42 |

Substitution budget: `{instruction}` for `clearance` must be one of the three
canonical strings used by the app (`Continue`, `Proceed to static scale - lane N`,
`Stop for inspection`) so that VMS, app and SMS never disagree. With a 7-char
plate, 8-char station and the longest instruction the `clearance` SMS is
~95 chars, leaving room for a `[SIMULATED]` suffix (12 chars) when
`source != live`. `notify()` already truncates to 160 (`body[:160]`).

### 4.2 Proposed additional templates (<= 160 chars)

| Key | Template | Purpose |
|---|---|---|
| `otp` | `KIFARU: Your verification code is {code}. Valid 5 min. Do not share.` | MSISDN verification before USSD self-service is enabled |
| `ussd_clearance` | `KIFARU: {plate} {decision} {station} {time}. {instruction} {source_tag}` | copy of a USSD answer for drivers who want a record |
| `slot_reminder` | `KIFARU: {plate} slot {slot} at {station} in 30 min. Queue {queue}, wait ~{wait} min.` | T-30 reminder (worker job) |
| `appointment_missed` | `KIFARU: {plate} missed slot {slot} at {station}. Dial *384*54327# to rebook.` | after `missed` status |
| `static_result` | `KIFARU: {plate} static scale {gvm} kg at {station}: {result}. Ticket {ref}.` | after `POST /weighing/events/{id}/static-verify` |
| `optout_ack` | `KIFARU: You will no longer receive SMS. Reply START to resume.` | STOP handling |

Kiswahili variants are produced by the same template keys with the user's
language preference (`sw`), e.g. `clearance` -> `KIFARU: {plate} {decision} {station}. {instruction}` with the Kiswahili decision words.

### 4.3 Delivery rules

* Channel selection: `ws` always; `sms` when the user has a verified phone and
  has not opted out; never both SMS and USSD push for the same event.
* Idempotency: one `Notification` row per (template, entity id, channel); the
  provider `messageId` is stored in `provider_ref` (already done in `send_sms`).
* Rate limit: max 1 `clearance` SMS per vehicle per 10 min; `queue.updated` is
  never sent by SMS.
* Opt-out: `STOP` is honoured for all marketing (`backhaul`) and informational
  templates; `otp` and `clearance` for an active appointment are still sent as
  they are transactional - this must be confirmed with legal.

## 5. Backend endpoints required

### 5.1 Already exist (reusable by a USSD/SMS gateway service)

| Endpoint | Used for | Notes |
|---|---|---|
| `GET /api/v1/weighing/events?vehicle_id=&limit=1` | clearance by plate (after plate -> vehicle resolution) | auth required, org-scoped |
| `GET /api/v1/fleet/vehicles` | plate -> vehicle id within the caller's org | auth required |
| `GET /api/v1/shipments/{reference}` | shipment by reference (accepts `KP-...`) | auth required, visibility rules |
| `GET /api/v1/stations` | station list with queue length / wait | auth required |
| `GET /api/v1/queue/{station}/slots` | next 15-min windows | auth required |
| `POST /api/v1/queue/{station}/appointments` | book slot | roles: driver, dispatcher, transporter_admin... |
| `GET /api/v1/queue/appointments/mine` | my appointment | org-scoped |
| `GET /api/v1/notifications/templates/sms` | template catalogue | auth required |
| `POST /api/v1/notifications/send` | send SMS via the mock/real Africa's Talking adapter | admin/dispatcher roles |
| `GET /api/v1/tickets/verify/{qr_token}` | public ticket check (could back an SMS `VERIFY <token>` keyword) | public |

### 5.2 Required - do not exist yet

| Endpoint | Purpose | Design notes |
|---|---|---|
| `POST /api/v1/ussd/callback` | Aggregator webhook (`sessionId`, `serviceCode`, `phoneNumber`, `text`). Returns `CON ...` / `END ...` plain text. | Authenticate the aggregator (HMAC header or IP allow-list + shared secret from Secrets Manager). Session state in Redis keyed by `sessionId` (TTL 180 s). Map `phoneNumber` -> `User` via a **hash of the MSISDN** (new `UserPII.phone_hash` column; `phone_enc` is encrypted and not searchable). Act with that user's roles via an internal principal; never platform-wide. |
| `POST /api/v1/sms/inbound` | Inbound SMS keywords: `STOP`, `START`, `HELP`, `KIFARU <plate>`, `VERIFY <token>` | Same auth as above. `STOP` writes an opt-out flag (new `UserPII.sms_opt_out_at`). |
| `POST /api/v1/sms/dlr` | Delivery reports | Update `Notification.status` by `provider_ref`; audit failures. |
| `POST /api/v1/auth/phone/verify-start` and `/verify-confirm` | OTP flow binding an MSISDN to a user before USSD is allowed | Uses the `otp` template; 5-minute validity; 3 attempts; rate-limited. Required because the USSD channel has no password. |
| Internal `GET /api/v1/fleet/vehicles/by-plate/{plate}` (service-only) | Plate -> vehicle for the gateway without listing the whole fleet | Must reuse `normalise_plate()`; restricted to the caller's org; **not public** to avoid plate enumeration. |
| Internal `GET /api/v1/queue/appointments/by-plate/{plate}` (service-only) | "My appointment" over USSD | Org-scoped as above. |
| Worker job `slot_reminder` | T-30 reminder SMS | Reads appointments with `slot_start` in 30 +/- 1 min, idempotent per appointment. |

### 5.3 Data-protection notes (Kenya DPA 2019)

* The MSISDN is PII: store it encrypted (`phone_enc`, existing) plus a keyed
  hash for lookup; log only the last 3 digits.
* USSD and SMS are clear-text channels: never include names, ID numbers,
  consignee details or full declaration references; plates and shipment
  references (`KP-...`) are considered operational identifiers.
* Keep the `source` tag on any SMS/USSD weighing text; simulated data must not
  be mistaken for a legal reading, and the pre-screen disclaimer stays.

## 6. Message flow (happy path)

```
Driver dials *384*54327#
  -> MNO -> aggregator -> POST /ussd/callback {phoneNumber, text=""}
  -> API: hash(MSISDN) -> user (driver, org T1) -> language -> main menu (CON)
Driver sends "1" then "KBZ123A"
  -> API: normalise plate -> vehicle in org T1 -> latest weighing -> decision
  -> END "KBZ 123A: AMBER at MSA-WIM1 14:32. Proceed to static scale lane 9."
  -> notify(template="ussd_clearance", channels=("sms",))  (optional copy)
```

## 7. Open questions

1. Short-code and USSD sub-code allocation timeline and cost (aggregator + CA).
2. Whether `clearance` SMS should be sent at all for GREEN (noise vs. record).
3. Static lane assignment must come from the edge/engine (API gap #2 in the
   mobile README) so USSD, SMS, VMS and the app all say the same lane.
4. Kiswahili wording review by operations staff at the pilot station.
