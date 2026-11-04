"""Polling fallback for the live feed (platforms without WebSockets, e.g. serverless hosting).

GET /api/v1/events/recent rebuilds the most recent event envelopes from the database (clearance decisions, queue
observations, incidents, cargo stage changes) with deterministic event ids so clients can merge them with WebSocket
events without duplicates. Tenant scoping mirrors the WebSocket filter.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Query
from sqlalchemy import select

from ..deps import CurrentUser, DbDep, org_scope
from ..models import CargoProcessingEvent, ClearanceDecision, Incident, QueueRecord, Shipment, Vehicle, WeighingEvent, WeighingStation, utcnow
from ..services.weighing_service import INSTRUCTIONS

router = APIRouter(prefix="/events", tags=["realtime"])


def _iso(dt: datetime) -> str:
    return (dt if dt.tzinfo else dt.replace(tzinfo=utcnow().tzinfo)).isoformat()


@router.get("/recent")
def recent_events(p: CurrentUser, db: DbDep, minutes: int = Query(30, ge=1, le=720), types: str | None = None, station: str | None = None, limit: int = Query(100, le=300)):
    since = utcnow() - timedelta(minutes=minutes)
    wanted = set(types.split(",")) if types else None
    scope = org_scope(p)
    out: list[dict] = []
    stations = {s.id: s for s in db.execute(select(WeighingStation)).scalars()}

    def want(t: str) -> bool:
        return wanted is None or t in wanted

    if want("clearance.decided") or want("weighing.completed") or want("truck.diverted") or want("truck.released"):
        q = select(WeighingEvent, ClearanceDecision).join(ClearanceDecision, ClearanceDecision.weighing_event_id == WeighingEvent.id).where(WeighingEvent.occurred_at >= since)
        if station:
            q = q.where(WeighingEvent.station_id == station)
        if scope:
            q = q.join(Vehicle, Vehicle.id == WeighingEvent.vehicle_id).where(Vehicle.org_id == scope)
        rows = db.execute(q.order_by(WeighingEvent.occurred_at.desc()).limit(limit)).all()
        vehicles = {v.id: v for v in db.execute(select(Vehicle).where(Vehicle.id.in_({e.vehicle_id for e, _ in rows if e.vehicle_id}))).scalars()} if rows else {}
        for ev, dec in rows:
            v = vehicles.get(ev.vehicle_id) if ev.vehicle_id else None
            st = stations.get(ev.station_id)
            payload = {
                "weighing_event_id": ev.id, "decision_id": dec.id, "decision": dec.decision, "instruction": INSTRUCTIONS.get(dec.decision, ""),
                "plate": v.plate if v else (ev.identity.anpr_plate if ev.identity else None), "vehicle_id": ev.vehicle_id, "shipment_id": ev.shipment_id,
                "gvm_kg": ev.gvm_kg, "u_kg": ev.gvm_uncertainty_kg, "axle_config": ev.detected_axle_config, "lane_id": ev.lane_id,
                "station_code": st.code if st else None, "ticket_id": dec.ticket.id if dec.ticket else None, "ticket_qr_token": dec.ticket.qr_token if dec.ticket else None,
                "latency_ms": dec.latency_ms, "source": ev.source, "rules_fired": [r.get("rule") for r in dec.rules_fired],
            }
            org_id = v.org_id if v else "platform"
            for t in ("weighing.completed", "clearance.decided", "truck.diverted" if dec.decision != "GREEN" else "truck.released"):
                if want(t):
                    out.append({"event_id": f"db-{t}-{ev.id}", "type": t, "occurred_at": _iso(dec.decided_at), "station_id": ev.station_id, "org_id": org_id, "payload": payload, "producer": ev.source, "schema_version": 1})
    if want("queue.updated"):
        q = select(QueueRecord).where(QueueRecord.kind == "observed", QueueRecord.ts >= since)
        if station:
            q = q.where(QueueRecord.station_id == station)
        for r in db.execute(q.order_by(QueueRecord.ts.desc()).limit(limit)).scalars():
            st = stations.get(r.station_id)
            out.append({"event_id": f"db-queue-{r.id}", "type": "queue.updated", "occurred_at": _iso(r.ts), "station_id": r.station_id, "org_id": None,
                        "payload": {"station_id": r.station_id, "code": st.code if st else None, "queue_len": r.queue_len, "avg_wait_s": r.avg_wait_s, "utilisation": r.utilisation, "source": r.source},
                        "producer": r.source, "schema_version": 1})
    if want("incident.opened") or want("station.failure"):
        for i in db.execute(select(Incident).where(Incident.opened_at >= since).order_by(Incident.opened_at.desc()).limit(limit)).scalars():
            t = "station.failure" if i.category == "station_failure" else "incident.opened"
            if want(t):
                out.append({"event_id": f"db-incident-{i.id}", "type": t, "occurred_at": _iso(i.opened_at), "station_id": i.station_id, "org_id": None,
                            "payload": {"incident_id": i.id, "title": i.title, "severity": i.severity, "category": i.category, "station_id": i.station_id, "status": i.status},
                            "producer": "cloud-api", "schema_version": 1})
    if want("cargo.status_changed"):
        q = select(CargoProcessingEvent, Shipment).join(Shipment, Shipment.id == CargoProcessingEvent.shipment_id).where(CargoProcessingEvent.occurred_at >= since)
        if scope:
            q = q.where((Shipment.owner_org_id == scope) | (Shipment.transporter_org_id == scope))
        for e, s in db.execute(q.order_by(CargoProcessingEvent.occurred_at.desc()).limit(limit)).all():
            out.append({"event_id": f"db-cargo-{e.id}", "type": "cargo.status_changed", "occurred_at": _iso(e.occurred_at), "station_id": None, "org_id": s.owner_org_id,
                        "payload": {"shipment_id": s.id, "reference": s.reference, "stage": e.stage, "status": e.status}, "producer": "cloud-api", "schema_version": 1})
    out.sort(key=lambda e: e["occurred_at"])
    return out[-limit:]
