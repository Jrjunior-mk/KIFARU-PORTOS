"""Worker tests: ingest handlers called directly (no broker), dead-lettering, periodic jobs."""
from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy import select
from ulid import ULID

from kifaru.db import get_sessionmaker
from kifaru.models import Incident, Lane, QueueRecord, Sensor, Shipment, WeighingEvent, WeighingStation
from kifaru.workers import jobs
from kifaru.workers.mqtt_ingest import dispatch, handle_event_message, handle_health_message
from kifaru.workers.sqs_ingest import handle_sqs_body, topic_and_payload

from .conftest import h

API = "/api/v1"


def _measurement(gvm: int = 34400) -> dict:
    return {
        "speed_mps": 18.0, "gvm_kg": gvm, "gvm_u_kg": 900, "axle_config": "1+1+2", "class_code": "HGV4", "quality_flags": [],
        "sensor_health": {"P1": {"status": "ok", "reasons": []}}, "pavement_temp_c": 31.0,
        "axles": [{"index": 0, "load_kg": 7700, "u_kg": 300, "group_no": 1}, {"index": 1, "load_kg": 9500, "u_kg": 400, "group_no": 2},
                  {"index": 2, "load_kg": 8600, "u_kg": 400, "group_no": 3}, {"index": 3, "load_kg": 8600, "u_kg": 400, "group_no": 3}],
    }


def _payload(device_id: str, eid: str | None = None) -> dict:
    return {"device_id": device_id, "edge_event_id": eid or str(ULID()), "occurred_at": datetime.now(UTC).isoformat(), "measurement": _measurement(),
            "anpr_plate": "KDA 412B", "anpr_confidence": 0.95, "rfid_epc": "E2000017221101441890A001", "rfid_confidence": 0.99}


def _lane(db) -> Lane:
    return db.execute(select(Lane).where(Lane.device_id == "gw-mrk-l1")).scalar_one()


def test_ingest_handler_creates_live_event_and_is_idempotent(client, operator, tmp_path):
    Session = get_sessionmaker()
    with Session() as db:
        lane = _lane(db)
        payload = _payload(lane.device_id)
        r1 = handle_event_message(db, json.dumps(payload).encode(), topic="kifaru/stations/MRK/lanes/1/events", dead_letter_directory=tmp_path)
        assert r1.status == "processed" and r1.decision == "GREEN" and r1.weighing_event_id
    with Session() as db:  # replay in a fresh session, as a redelivered QoS1 message would be
        r2 = handle_event_message(db, payload, dead_letter_directory=tmp_path)
        assert r2.status == "duplicate" and r2.weighing_event_id == r1.weighing_event_id
        ev = db.get(WeighingEvent, r1.weighing_event_id)
        assert ev.source == "live" and ev.edge_event_id == payload["edge_event_id"] and ev.decision is not None
        assert db.execute(select(WeighingEvent).where(WeighingEvent.edge_event_id == payload["edge_event_id"])).scalars().all().__len__() == 1
    # visible through the API with its source preserved
    r = client.get(f"{API}/weighing/events/{r1.weighing_event_id}", headers=h(operator))
    assert r.status_code == 200 and r.json()["source"] == "live" and r.json()["decision"]["decision"] == "GREEN"
    assert not list(tmp_path.glob("*.jsonl"))


def test_iot_rule_envelope_and_sqs_body_are_accepted(client, tmp_path):
    Session = get_sessionmaker()
    with Session() as db:
        lane = _lane(db)
        env = {"topic": "kifaru/stations/MRK/lanes/1/events", "payload": _payload(lane.device_id)}
        assert topic_and_payload(json.dumps(env))[0] == env["topic"]
        r = handle_sqs_body(db, json.dumps(env), dead_letter_directory=tmp_path)
        assert r.status == "processed"
        r = dispatch(db, "kifaru/stations/MRK/lanes/1/events", env, dead_letter_directory=tmp_path)
        assert r.status == "duplicate"


def test_malformed_messages_are_dead_lettered_without_exception(client, tmp_path):
    Session = get_sessionmaker()
    with Session() as db:
        lane = _lane(db)
        cases = [
            b"\xff\xfe not json",
            b"[1,2,3]",
            json.dumps({"device_id": lane.device_id}).encode(),  # missing fields
            json.dumps({**_payload(lane.device_id), "edge_event_id": "short"}).encode(),  # invalid ULID length
            json.dumps(_payload("gw-does-not-exist")).encode(),  # unknown device
            json.dumps({**_payload(lane.device_id), "measurement": {"gvm_kg": "x"}}).encode(),  # processing error inside the service
        ]
        for raw in cases:
            res = handle_event_message(db, raw, topic="kifaru/stations/MRK/lanes/1/events", dead_letter_directory=tmp_path)
            assert res.status == "dead_letter" and not res.ok, raw
        res = dispatch(db, "kifaru/stations/MRK/lanes/1/unknown", b"{}", dead_letter_directory=tmp_path)
        assert res.status == "dead_letter"
        # the session is still usable afterwards
        assert db.execute(select(WeighingStation)).scalars().first() is not None
    files = list(tmp_path.glob("*.jsonl"))
    assert len(files) == 1
    lines = [json.loads(l) for l in files[0].read_text(encoding="utf-8").splitlines()]
    assert len(lines) == len(cases) + 1
    assert all("reason" in l and "raw" in l and "topic" in l for l in lines)
    assert any("unknown device_id" in l["reason"] for l in lines) and any("validation" in l["reason"] for l in lines) and any("processing" in l["reason"] for l in lines)


def test_health_message_updates_sensor_status(client, tmp_path):
    Session = get_sessionmaker()
    with Session() as db:
        lane = _lane(db)
        serial = next(s.serial for s in lane.sensors if s.kind == "bending_plate")
        msg = {"device_id": lane.device_id, "reported_at": datetime.now(UTC).isoformat(), "sensors": {serial: {"status": "fault", "reason": "baseline drift 14 %"}, "P1": {"status": "degraded", "reason": "noise"}, "ZZZ": {"status": "ok"}}}
        res = handle_health_message(db, json.dumps(msg).encode(), dead_letter_directory=tmp_path)
        assert res.status == "health_updated" and "2 sensors updated" in res.detail and "ZZZ" in res.detail
    with Session() as db:
        lane = _lane(db)
        bp = next(s for s in lane.sensors if s.kind == "bending_plate")
        p1 = next(s for s in lane.sensors if s.kind == "piezo_quartz" and abs(s.install_position_m - 4.0) < 0.01)
        assert bp.status == "fault" and bp.health_reason == "baseline drift 14 %" and bp.last_reading_at is not None
        assert p1.status == "degraded" and lane.status == "degraded"
        # restore
        res = handle_health_message(db, {"device_id": lane.device_id, "sensors": {bp.serial: {"status": "ok"}, "P1": {"status": "ok"}}}, dead_letter_directory=tmp_path)
        assert res.status == "health_updated"
    with Session() as db:
        lane = _lane(db)
        assert all(s.status == "ok" for s in lane.sensors) and lane.status == "operational"
    assert handle_health_message(Session(), b"{bad", dead_letter_directory=tmp_path).status == "dead_letter"


def test_jobs_run_once_populates_forecasts_predictions_and_incidents(client):
    Session = get_sessionmaker()
    with Session() as db:
        st = db.execute(select(WeighingStation).where(WeighingStation.code == "MRK")).scalar_one()
        # a congested observation so the incident agent has something to say (queue > hourly capacity)
        db.add(QueueRecord(station_id=st.id, ts=datetime.now(UTC), kind="observed", queue_len=st.capacity_per_hour + 40, avg_wait_s=3600, utilisation=1.0, arrivals_per_hour=st.capacity_per_hour * 1.3, source="simulated"))
        bp = db.execute(select(Sensor).join(Lane).where(Lane.station_id == st.id, Sensor.kind == "bending_plate")).scalars().first()
        bp.status, bp.health_reason = "fault", "test fault"
        db.commit()
        n_fc_before = len(db.execute(select(QueueRecord).where(QueueRecord.kind.like("forecast_%"))).scalars().all())
        summary = jobs.run_once(db)
        assert summary["stations_forecast"] == len(db.execute(select(WeighingStation)).scalars().all())
        assert summary["forecast_records"] == summary["stations_forecast"] * 4
        assert summary["shipments_predicted"] >= 3
    with Session() as db:
        n_fc_after = len(db.execute(select(QueueRecord).where(QueueRecord.kind.like("forecast_%"))).scalars().all())
        assert n_fc_after == n_fc_before + summary["forecast_records"]
        kinds = {r.kind for r in db.execute(select(QueueRecord).where(QueueRecord.station_id == st.id, QueueRecord.kind.like("forecast_%"))).scalars()}
        assert kinds == {"forecast_15", "forecast_30", "forecast_60", "forecast_120"}
        for sh in db.execute(select(Shipment).where(Shipment.status == "active")).scalars():
            assert sh.predicted_release_p10 is not None and sh.predicted_release_at is not None and sh.predicted_release_p90 is not None
            assert sh.predicted_release_p10 <= sh.predicted_release_at <= sh.predicted_release_p90
            assert sh.prediction_explanation["label"] == "advisory prediction" and "reasons" in sh.prediction_explanation
        incidents = db.execute(select(Incident).where(Incident.station_id == st.id, Incident.status == "open")).scalars().all()
        titles = [i.title for i in incidents]
        assert any(t.startswith("Sensor fault") for t in titles) and any(t.startswith("Queue") for t in titles)
        assert all(i.raised_by == "operational_incident_agent" and i.severity in ("high", "critical") for i in incidents)
        # second run must not duplicate open incidents
        summary2 = jobs.run_once(db)
        assert summary2["incidents_opened"] == 0
        assert len(db.execute(select(Incident).where(Incident.station_id == st.id, Incident.status == "open")).scalars().all()) == len(incidents)
        # cleanup so other tests see a healthy station
        bp = db.execute(select(Sensor).join(Lane).where(Lane.station_id == st.id, Sensor.kind == "bending_plate")).scalars().first()
        bp.status, bp.health_reason = "ok", None
        db.commit()
