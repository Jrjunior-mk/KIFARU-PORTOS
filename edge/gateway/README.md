# `edge/gateway` — KIFARU PORTOS Roadside Gateway (Python)

Runs on the lane IPC. Receives DAQ frames (CAN-FD/UDP, `daq_client.py`), fuses identity (ANPR/RFID adapters,
`identity.py`), decides locally with the **same engine as the cloud API** (`clearance_mirror.py` imports
`kifaru.services.clearance_engine.decide` against a cached snapshot), drives the lane signal/VMS (`vms.py`, Modbus RTU),
and stores every event in a SQLite WAL outbox (`outbox.py`) that is replayed in order over MQTT 5/mTLS with an HTTP
`/api/v1/weighing/ingest` fallback (`uplink.py`). CLD-04: no event is lost during an outage; the cloud ingest is
idempotent on the ULID `edge_event_id`.

## Run

```powershell
cd kifaru-portos
.venv\Scripts\python.exe -m pip install -e edge/gateway            # or run from the folder with PYTHONPATH=edge/gateway
.venv\Scripts\python.exe -m kifaru_gateway.main --simulate --rate 2 --count 20 --seed 1
.venv\Scripts\python.exe -m kifaru_gateway.main --udp 0.0.0.0:5010 --uplink auto --mqtt-host <broker> --mqtt-ca ca.pem --mqtt-cert gw.pem --mqtt-key gw.key --http-url https://api... --http-token <jwt>
```

`--simulate` uses `kifaru_wim_dsp.generate_pass` + `process_pass` (every payload is tagged `source=simulated`) with a demo
vehicle registry (`demo_snapshot()`); real deployments receive the snapshot on the `cmd` topic and cache it in
`<data-dir>/snapshot.json`.

## Tests

```powershell
.venv\Scripts\python.exe -m pytest edge/gateway/tests -q
```

* `test_outbox.py` — enqueue 50 events while the uplink is down, exponential backoff, ordered replay, no duplicates,
  idempotent re-enqueue, persistence across restart, poison parking.
* `test_clearance_mirror.py` — mirror decision == direct `clearance_engine.decide` (same evidence hash); conflict/watch-list
  RED; unknown vehicle / expired calibration AMBER; certain overload RED.
* `test_frames.py` — byte sizes of every payload, CRC-32 check value, UDP wrap/unwrap/corruption, measurement → frames →
  assembler → measurement (UDP and CAN-FD paths).
* `test_gateway_pipeline.py` — simulated DAQ → identity → decision → VMS → outbox → uplink, `EdgeIngestIn` shape.
* `test_vms.py` — Modbus RTU CRC, register writes, custom text, fault reporting.

## Layout

```
kifaru_gateway/
  config.py            GatewayConfig (env KIFARU_GW_*), topics kifaru/stations/{station}/lanes/{lane}/{events,health,cmd}
  daq_client.py        frame codec, PassAssembler, UdpDaqClient (+TIME_SYNC), SimulatedDaq, measurement<->frames
  identity.py          AnprRead/RfidRead, MockAnpr/MockRfid, PaddleOcrAnpr (RTSP+YOLOv8+PaddleOCR), LlrpRfid (sllurp), rfid_confidence()
  clearance_mirror.py  Snapshot (limits, registry, tags, watch-list, calibration validity), identity resolution mirror, decide()
  outbox.py            SQLite WAL outbox, ULIDs, backoff, ordered drain, poison parking
  uplink.py            MqttUplink (paho, MQTT 5, TLS/mTLS, retained health, LWT), HttpUplink (EdgeIngestIn POST), CompositeUplink, MemoryUplink
  vms.py               Modbus RTU codec, MockModbusBackend, SerialModbusBackend (pyserial), VmsController
  main.py              CLI and Gateway orchestration
tools/accuracy_table.py  truth-vs-measured table from gateway logs (lab rig / calibration)
```

Field-only dependencies (not installed here): `pyserial`, `sllurp`, `opencv-python-headless`, `paddleocr`, `ultralytics`.
