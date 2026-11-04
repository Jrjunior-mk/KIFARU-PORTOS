# Communications Interfaces (HW-11)

This document is the single source of truth for every byte on the wire between the DAQ, the auxiliary node, the
gateway, the roadside devices and the cloud. The firmware (`firmware/stm32-wim-daq/App/frames.c`), the ESP32 node and
the gateway parser (`edge/gateway/kifaru_gateway/daq_client.py`) implement exactly the layouts below; the gateway test
`tests/test_frames.py` round-trips them.

```
DAQ (STM32H743) ===CAN-FD 500k/2M===> gateway   (primary: deterministic, isolated)
DAQ (STM32H743) ===UDP/IPv4 binary==> gateway   (secondary/high-volume: same payloads + header + CRC-32)
ESP32 aux       ===CAN (classic 500k)=> DAQ and gateway (environment, power, door)
gateway         ===MQTT 5 / TLS 1.2+ mTLS===> cloud broker (AWS IoT Core / EMQX)
gateway         ===HTTPS POST /api/v1/weighing/ingest===> cloud API (fallback when MQTT is unavailable)
gateway  <===RTSP/ONVIF===  ANPR cameras ;  gateway <===LLRP (TCP 5084)=== RFID reader
gateway/DAQ ===RS-485 Modbus RTU===> VMS / lane signal ;  DAQ <===RS-485=== radar
GPS receiver ---PPS---> DAQ TIM2 capture ; ---NMEA---> gateway (chrony/gpsd) ; NTP -> gateway
```

---

## 1. Common payload definitions (shared by CAN-FD and UDP)

All integers little-endian. Timestamps `t_us` are unsigned 64-bit microseconds. Before the DAQ has received a
TIME_SYNC they count from boot; after it they are UTC microseconds (Unix epoch). Lengths are fixed per message type
except PASS_SUMMARY and HEALTH, which carry a count.

| Type | Name | Direction | Size (B) | CAN-FD OK (≤ 64 B) |
|---|---|---|---|---|
| 0x01 | AXLE_EVENT | DAQ → GW | 52 | yes |
| 0x02 | PASS_SUMMARY | DAQ → GW | 38 + 8·n_axles (UDP) / 38 (CAN-FD, axles come as AXLE_EVENTs) | yes (fixed part) |
| 0x03 | HEALTH | DAQ → GW | 10 + 6·n_ch | yes (n_ch ≤ 8 per frame) |
| 0x04 | LOOP_EVENT | DAQ → GW | 12 | yes |
| 0x05 | IR_EVENT | DAQ → GW | 12 | yes |
| 0x06 | ENV | ESP32 → DAQ/GW | 22 | yes |
| 0x07 | TIME_SYNC | GW → DAQ | 12 | yes |
| 0x08 | HEARTBEAT | DAQ → GW | 17 | yes |

### 1.1 AXLE_EVENT (0x01) — one per detected axle, emitted as soon as the axle has crossed the last row

```
offset  type  field
0       u32   pass_id              DAQ-local incrementing pass counter (wraps)
4       u8    axle_index           0-based
5       u8    rows_valid           bit0 P1, bit1 P2, bit2 P3, bit3 BP
6       u8    flags                bit0 saturation, bit1 lr_asym (>30 % left/right mismatch), bit2 merged_pulse
7       u8    reserved
8       u64   t_p1_us              peak time at row P1 (0 if not detected)
16      u64   t_p2_us
24      u64   t_p3_us
32      u64   t_bp_us
40      u16   load_p1_kg           per-row load estimate (left+right), 0 if not detected
42      u16   load_p2_kg
44      u16   load_p3_kg
46      u16   load_bp_kg
48      u16   speed_cmps           axle speed from P1→P2 (cm/s)
50      u16   spacing_prev_mm      distance to previous axle (0 for the first axle), capped 65535
```

### 1.2 PASS_SUMMARY (0x02) — emitted when L3 clears (or 2 s after the last axle)

```
0       u32   pass_id
4       u64   t_first_axle_us      time of first axle at P1 (used as occurred_at)
12      u8    axle_count
13      u8    n_groups
14      u16   quality_flags        bitmask, see §1.9
16      u16   speed_cmps
18      u16   speed_u_cmps         expanded (k=2) speed uncertainty
20      u32   gvm_kg
24      u32   gvm_u_kg             expanded (k=2)
28      i16   pavement_temp_c_x10
30      u8[8] sensor_health        one byte each for P1, P2, P3, BP, L1, L2, L3, IR: 0 ok, 1 degraded, 2 fault, 255 n/a
38      n × { u16 load_kg; u16 u_kg; u16 spacing_next_mm (0xFFFF = none); u8 group_no; u8 pad }   (UDP only)
```

The gateway converts this (plus the AXLE_EVENTs for `per_row_kg`) into the `WimMeasurement.to_dict()` shape consumed
by `POST /api/v1/weighing/ingest` (`measurement` field of `EdgeIngestIn`).

### 1.3 HEALTH (0x03) — every 10 s in idle, and after every pass

```
0       u64   t_us
8       u8    first_channel        0..15 (0..5 piezo P1L..P3R, 6..7 BP L/R, 8 EXC monitor, 9 AFE temp, 10..15 spare)
9       u8    n_ch
10      n_ch × { u16 noise_rms_kg_x10; i16 baseline_kg; u8 status (0/1/2); u8 flags (bit0 dead, bit1 saturated, bit2 noisy, bit3 drift, bit4 hum50) }
```

### 1.4 LOOP_EVENT (0x04) / IR_EVENT (0x05)

```
0       u64   t_us
8       u8    id                   loop 1..3 / beam 1..4
9       u8    state                1 = occupied/blocked, 0 = clear
10      u16   reserved
```

### 1.5 ENV (0x06) — from the ESP32 aux node every 10 s

```
0       u64   t_us
8       i16   pavement_c_x100      PT1000 via MAX31865
10      i16   ambient_c_x100       SHT4x outside
12      u16   rh_x100              SHT4x outside
14      i16   cabinet_c_x100       SHT4x inside
16      u16   bus_mv               24 V bus
18      u16   batt_mv              battery
20      u8    digital              bit0 door_open, bit1 ac_fail, bit2 batt_low, bit3 spd_fault, bit4 fan_on
21      u8    reserved
```

### 1.6 TIME_SYNC (0x07) — gateway → DAQ after each PPS (or every 1 s without GPS)

```
0       u64   utc_us_at_pps        UTC microseconds of the most recent PPS edge (whole second when GPS-locked)
8       u32   pps_count            gateway's PPS counter; the DAQ matches it with its own TIM2 capture count
```

### 1.7 HEARTBEAT (0x08) — every 1 s

```
0       u64   t_us
8       u32   uptime_s
12      u32   fw_version           0xMMmmpppp
16      u8    state                0 boot, 1 idle, 2 vehicle_present, 3 fault
```

### 1.8 CAN-FD identifiers

11-bit standard IDs, `ID = 0x100 + 0x20·lane_no + msg_type` for DAQ → gateway (lane_no 0..3), `0x180 + 0x20·lane_no +
msg_type` for gateway → DAQ, `0x200 + 0x20·lane_no + msg_type` for the ESP32 node. Lower IDs (AXLE_EVENT, PASS_SUMMARY)
win arbitration over HEALTH. Nominal bit rate 500 kbit/s, data phase 2 Mbit/s, BRS set, 64-byte frames, ISO CRC. The
ESP32 uses classic CAN 2.0B at 500 kbit/s (its TWAI controller is not FD-capable on ESP32/ESP32-S3, D) and its 22-byte
ENV payload is split into frames 0x206 (bytes 0–7), 0x207 (8–15), 0x208 (16–21); the DAQ reassembles and forwards it as
a 0x06 payload on both of its links.

Priority/latency (C): an AXLE_EVENT of 52 B at 2 Mbit/s data phase + ~30 arbitration bits at 500 kbit/s takes
≈ 0.3 ms; a 5-axle pass produces 5 + 1 frames, i.e. < 2 ms of bus time; the bus is idle > 99 % of the time.

### 1.9 quality_flags bitmask (u16) and their string names in the API

| bit | name (API string) |
|---|---|
| 0 | sensor_fault |
| 1 | sensor_degraded |
| 2 | speed_unavailable |
| 3 | speed_out_of_range |
| 4 | insufficient_rows |
| 5 | axle_load_missing |
| 6 | high_uncertainty |
| 7 | no_axles_detected |
| 8 | saturation (gateway maps to `sensor_fault` as well) |
| 9 | loop_inconsistent (mapped to `sensor_degraded`) |
| 10 | speed_inconsistent (mapped to `sensor_degraded`) |
| 11 | pavement_hot (mapped to `sensor_degraded`) |

---

## 2. UDP binary framing (DAQ ↔ gateway, port 5010)

```
offset  type  field
0       u16   magic   = 0x4B57 ("KW")
2       u8    version = 1
3       u8    msg_type
4       u16   seq               per-sender incrementing (gap detection)
6       u16   payload_len
8       u32   t_tx_us_low       low 32 bits of the sender's t_us at transmission (latency monitoring)
12      u8[payload_len]  payload (as §1)
12+n    u32   crc32             IEEE 802.3 CRC-32 (poly 0x04C11DB7 reflected = 0xEDB88320, init 0xFFFFFFFF, final XOR
                                0xFFFFFFFF; identical to zlib.crc32) over bytes 0 .. 12+n−1
```

Maximum frame: 12 + 134 + 4 = 150 B (PASS_SUMMARY with 12 axles); no fragmentation. The DAQ sends to the gateway's
unicast address (configured) from port 5010; the gateway sends TIME_SYNC to the DAQ's port 5011. Loss is tolerated
because the CAN-FD copy is primary; the gateway de-duplicates on (device_id, pass_id, msg_type, axle_index). The STM32
uses lwIP raw UDP; link 100BASE-TX through the isolated switch port.

---

## 3. Gateway ↔ cloud: MQTT 5 over TLS with mutual authentication

| Item | Setting |
|---|---|
| Broker | AWS IoT Core endpoint (af-south-1) or EMQX; port 8883 |
| TLS | 1.2 minimum, 1.3 preferred; server CA pinned (Amazon Root CA 1 / own CA); client X.509 device certificate + key (per gateway, stored in the IPC TPM or file with 0600) |
| Client ID | `gw-{station}-{lane}` (must equal the certificate's CN / IoT thing name for the policy to allow it) |
| Keep-alive | 60 s; clean start = false (session expiry 7 days) so QoS-1 inflight messages survive reconnects |
| Topics | `kifaru/stations/{station}/lanes/{lane}/events` (QoS 1, not retained) — one message per event; `kifaru/stations/{station}/lanes/{lane}/health` (QoS 1, **retained**) — latest health snapshot; `kifaru/stations/{station}/lanes/{lane}/cmd` (subscribe, QoS 1) — limits/watch-list snapshot pushes and config |
| Payload | JSON (UTF-8); `event_id` is a 26-char ULID created at the edge (`EdgeIngestIn.edge_event_id`); the measurement payload is exactly `EdgeIngestIn` so the cloud ingest worker forwards it to `POST /api/v1/weighing/ingest` unchanged |
| MQTT 5 properties | `Message Expiry Interval` 7 days on events; `User Property` `schema=1`, `producer=gw-...`; `Response Topic` unused |
| Ordering | one in-flight publish at a time from the outbox (strictly ordered replay), so the cloud sees ULID order |
| Last Will | retained health message with `"status":"offline"` on the health topic |

Event envelope on the `events` topic:

```json
{
  "event_id": "01J9...ULID",
  "type": "weighing.completed",
  "occurred_at": "2026-11-04T08:15:42.123456+00:00",
  "station_id": "MARIAKANI", "lane_id": "L1", "producer": "gw-MARIAKANI-L1", "schema_version": 1,
  "payload": { ...EdgeIngestIn fields..., "edge_decision": {"decision": "AMBER", "evidence_hash": "...", "engine_version": "clr-1.2.0"} }
}
```

Event `type` values are the API's `EventType` names (`truck.detected`, `truck.identified`, `weighing.completed`,
`clearance.decided`, `sensor.health`, `station.failure`). The edge decision is advisory for the cloud (the cloud engine
re-decides with the authoritative registry); the gateway records both so a mismatch becomes an incident.

HTTP fallback: when the broker is unreachable for > 60 s but the API is (e.g. broker outage), the uplink POSTs each
`weighing.completed` payload to `/api/v1/weighing/ingest` with a bearer token; `201` and `200` are both success (the
API is idempotent on `edge_event_id`), `4xx` other than `409/429` is a poison message (parked, alarmed), `5xx`/timeouts
retry with exponential backoff (1 s → 60 s, jitter ±20 %).

---

## 4. ANPR cameras: ONVIF + RTSP

* Discovery/config: ONVIF Profile S/T (WS-Discovery on UDP 3702; device service on `http://cam/onvif/device_service`);
  set time via ONVIF `SetSystemDateAndTime` from the gateway's NTP-disciplined clock every hour (camera RTC drift matters
  for frame-to-axle association).
* Streams: RTSP `rtsp://cam:554/Streaming/Channels/101` (vendor path), H.264 1920×1080 25 fps main stream for OCR;
  substream 704×576 for the dashboard. The gateway pulls with GStreamer/ffmpeg into OpenCV; latency budget 150 ms.
* Trigger: the gateway opens a capture window when LOOP_EVENT L1 = occupied (front camera) and when L3 = clear (rear
  camera), ±0.8 s, and runs detection + OCR on the frames in the window; the best read (highest OCR confidence on a plate
  that passes the Kenyan-format regex `^K[A-Z]{2} ?\d{3}[A-Z]$` or the EAC foreign formats) is reported as `anpr_plate`,
  `anpr_confidence`.
* Interface in code: `kifaru_gateway.identity.AnprAdapter` (abstract) with `MockAnpr` (deterministic) and a documented
  `PaddleOcrAnpr` stub that expects `paddleocr` + `ultralytics` installed on the IPC.

## 5. RFID reader: LLRP

* LLRP (EPCglobal Low Level Reader Protocol) over TCP port 5084, reader is the server; the gateway adds an `ROSpec`
  with `ROSpecStartTrigger = Immediate`, antennas 1–2, session S2, `ROReportSpec` on every N tags = 1 with EPC, antenna
  ID, peak RSSI, first/last seen timestamps, tag seen count; `KeepaliveSpec` 10 s. Python: `sllurp` (Apache-2) is the
  intended client; the repository contains `MockRfid` and the `LlrpRfid` interface.
* Confidence model (gateway, deterministic): `conf = min(0.999, 0.6 + 0.08·min(seen_count, 4) + 0.02·clip((rssi + 70)/5, 0, 4))`
  — a tag read ≥ 4 times at −50 dBm gets 0.999; a single read at −70 dBm gets 0.68. Two different EPCs in the same pass
  window are reported with the RSSI-dominant one plus a `rfid_multiple` note; the engine's identity rules do the rest.
* Tags: ISO/IEC 18000-63 (EPC Gen2v2) windscreen tags; EPC-96 with the platform's company prefix; TID locked.

## 6. VMS / lane signal: RS-485 Modbus RTU

Serial 115200 8N1 (fallback 9600), slave address 1 (VMS), 2 (lane signal head). Holding registers (function 03 read,
06/16 write):

| Register | Name | Values |
|---|---|---|
| 40001 (0) | signal_state | 0 off, 1 GREEN, 2 AMBER, 3 RED, 4 flashing AMBER (fault) |
| 40002 (1) | vms_message_id | 0 blank, 1 "PROCEED", 2 "WEIGHBRIDGE →", 3 "STOP INSPECTION", 4 "SLOW", 5 custom text in 40010.. |
| 40003 (2) | plate_display_enable | 0/1 (show the plate read on the VMS) |
| 40004 (3) | hold_time_s | seconds to hold the message after the vehicle clears L3 (default 8) |
| 40005 (4) | brightness_pct | 0–100 (auto if 255) |
| 40006 (5) | heartbeat | gateway writes an incrementing counter every 1 s; the VMS blanks + flashing amber after 5 s silence |
| 40010–40041 (9–40) | custom_text | 32 registers, 2 ASCII chars each |
| 30001–30004 (input regs) | status: lamp fault bits, temperature, supply mV, firmware | read-only |

Decision → display mapping lives in `kifaru_gateway/vms.py` (`GREEN → 1/"PROCEED"`, `AMBER → 2/"WEIGHBRIDGE →"`,
`RED → 3/"STOP INSPECTION"`); the mock backend keeps the register file in memory and the real backend uses `pymodbus`
(not installed in this environment; the wire codec for 06/16 is implemented locally with CRC-16/Modbus so the mock can
be swapped for a serial port without the dependency).

## 7. Time synchronisation

```
GPS receiver (u-blox M8/M9 class, timing mode) --PPS (1 Hz, ±30 ns to UTC (D))--> STM32 TIM2 CH1 input capture (TIM2 32-bit @ 1 MHz)
                                             --NMEA/UBX (UART, USB)--> gateway gpsd -> chrony (PPS refclock) -> system clock ±1 µs
gateway --TIME_SYNC (utc_us_at_pps, pps_count)--> DAQ : DAQ sets  t_us = utc_us_at_pps + (TIM2_now − TIM2_capture)
gateway <--NTP (chrony) ---- pool/cloud NTP as holdover reference when GPS is lost (±1–10 ms); the DAQ keeps free-running
```

DAQ time base: TIM2 32-bit at 1 MHz (480 MHz / 480), wraps every 71.6 min; the firmware extends it to 64 bits in the
overflow interrupt. The ADS131M08 DRDY edge is captured by TIM2 CH2 so every sample has a hardware timestamp; axle peak
times are interpolated from sample index × 125 µs relative to the captured DRDY (the ADC's own 8.192 MHz crystal is
±25 ppm, so a 1 s pass accumulates ≤ 25 µs of drift between captures — negligible against speed accuracy).

Holdover: when no TIME_SYNC arrives for 10 min the DAQ sets `time_unsynced` in HEALTH flags (degraded only — speed and
loads are relative measurements and do not depend on absolute time; `occurred_at` accuracy then degrades to the
gateway's NTP accuracy because the gateway stamps arrival time).

## 8. Radar (RS-485)

Vendor ASCII or Modbus RTU at 9600–115200; the DAQ polls the speed register at 10 Hz on UART4 and keeps the last 2 s of
readings; `speed_inconsistent` is set when the radar speed during the pass differs from the two-row speed by > 5 %.
