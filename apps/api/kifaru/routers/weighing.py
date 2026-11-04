from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from ..config import get_settings
from ..deps import CurrentUser, DbDep, Principal, audit, org_scope, require_roles
from ..events import EventType, publish
from ..models import ClearanceDecision, Lane, Vehicle, WeighingEvent
from ..services import ledger, tickets
from ..services.limits import DEFAULT_LIMITS
from ..services.simulator import SimOptions, simulate_pass
from ..services.weighing_service import process_lane_pass

router = APIRouter(prefix="/weighing", tags=["weighing"])
OPS = require_roles("platform_admin", "weighbridge_operator", "port_controller")


class AxleOut(BaseModel):
    axle_index: int
    load_kg: int
    uncertainty_kg: int
    spacing_to_next_m: float | None
    group_no: int


class IdentityOut(BaseModel):
    anpr_plate: str | None
    anpr_confidence: float | None
    rfid_epc: str | None
    rfid_confidence: float | None
    confidence: float
    method: str
    explanation: str | None


class DecisionOut(BaseModel):
    id: str
    decision: str
    rules_fired: list
    margins: dict
    limits_version: str
    engine_version: str
    audit_selected: bool
    evidence_hash: str
    decided_at: datetime
    latency_ms: int
    explanation: str
    static_verified_gvm_kg: int | None
    override_reason: str | None
    ticket_id: str | None
    ticket_type: str | None
    qr_token: str | None


class WeighingOut(BaseModel):
    id: str
    station_id: str
    lane_id: str
    vehicle_id: str | None
    plate: str | None
    shipment_id: str | None
    occurred_at: datetime
    speed_mps: float
    gvm_kg: int
    gvm_uncertainty_kg: int
    axle_count: int
    detected_axle_config: str | None
    class_code: str | None
    quality_flags: list
    sensor_health: dict
    pavement_temp_c: float | None
    source: str
    kind: str
    axles: list[AxleOut]
    identity: IdentityOut | None
    decision: DecisionOut | None


def _out(db, ev: WeighingEvent, plates: dict[str, str] | None = None) -> WeighingOut:
    plate = None
    if ev.vehicle_id:
        if plates is not None:
            plate = plates.get(ev.vehicle_id)
        else:
            v = db.get(Vehicle, ev.vehicle_id)
            plate = v.plate if v else None
    elif ev.identity:
        plate = ev.identity.anpr_plate
    d = ev.decision
    ident = ev.identity
    return WeighingOut(
        id=ev.id, station_id=ev.station_id, lane_id=ev.lane_id, vehicle_id=ev.vehicle_id, plate=plate, shipment_id=ev.shipment_id,
        occurred_at=ev.occurred_at, speed_mps=ev.speed_mps, gvm_kg=ev.gvm_kg, gvm_uncertainty_kg=ev.gvm_uncertainty_kg,
        axle_count=ev.axle_count, detected_axle_config=ev.detected_axle_config, class_code=ev.class_code, quality_flags=ev.quality_flags,
        sensor_health=ev.sensor_health, pavement_temp_c=ev.pavement_temp_c, source=ev.source, kind=ev.kind,
        axles=[AxleOut(axle_index=a.axle_index, load_kg=a.load_kg, uncertainty_kg=a.uncertainty_kg, spacing_to_next_m=a.spacing_to_next_m, group_no=a.group_no) for a in ev.axles],
        identity=IdentityOut(anpr_plate=ident.anpr_plate, anpr_confidence=ident.anpr_confidence, rfid_epc=ident.rfid_epc, rfid_confidence=ident.rfid_confidence,
                             confidence=ident.confidence, method=ident.method, explanation=ident.explanation) if ident else None,
        decision=DecisionOut(id=d.id, decision=d.decision, rules_fired=d.rules_fired, margins=d.margins, limits_version=d.limits_version,
                             engine_version=d.engine_version, audit_selected=d.audit_selected, evidence_hash=d.evidence_hash, decided_at=d.decided_at,
                             latency_ms=d.latency_ms, explanation=d.explanation, static_verified_gvm_kg=d.static_verified_gvm_kg,
                             override_reason=d.override_reason, ticket_id=d.ticket.id if d.ticket else None, ticket_type=d.ticket.type if d.ticket else None,
                             qr_token=d.ticket.qr_token if d.ticket else None) if d else None,
    )


@router.get("/events", response_model=list[WeighingOut])
def list_events(p: CurrentUser, db: DbDep, station_id: str | None = None, vehicle_id: str | None = None, decision: str | None = None,
                limit: int = Query(50, le=500)):
    q = select(WeighingEvent).order_by(WeighingEvent.occurred_at.desc()).limit(limit)
    if station_id:
        q = q.where(WeighingEvent.station_id == station_id)
    if vehicle_id:
        q = q.where(WeighingEvent.vehicle_id == vehicle_id)
    if decision:
        q = q.join(ClearanceDecision).where(ClearanceDecision.decision == decision)
    scope = org_scope(p)
    if scope:
        q = q.join(Vehicle, Vehicle.id == WeighingEvent.vehicle_id).where(Vehicle.org_id == scope)
    rows = db.execute(q).scalars().all()
    ids = {e.vehicle_id for e in rows if e.vehicle_id}
    plates = {v.id: v.plate for v in db.execute(select(Vehicle).where(Vehicle.id.in_(ids))).scalars()} if ids else {}
    return [_out(db, e, plates) for e in rows]


@router.get("/events/{event_id}", response_model=WeighingOut)
def get_event(event_id: str, p: CurrentUser, db: DbDep):
    ev = db.get(WeighingEvent, event_id)
    if ev is None:
        raise HTTPException(404, "Not found")
    scope = org_scope(p)
    if scope:
        v = db.get(Vehicle, ev.vehicle_id) if ev.vehicle_id else None
        if v is None or v.org_id != scope:
            raise HTTPException(404, "Not found")
    return _out(db, ev)


class StatsOut(BaseModel):
    total: int
    by_decision: dict[str, int]
    by_source: dict[str, int]
    mean_latency_ms: float
    green_rate: float
    stops_avoided: int


@router.get("/stats", response_model=StatsOut)
def stats(p: CurrentUser, db: DbDep, station_id: str | None = None):
    q = select(ClearanceDecision.decision, func.count()).join(WeighingEvent, WeighingEvent.id == ClearanceDecision.weighing_event_id)
    if station_id:
        q = q.where(WeighingEvent.station_id == station_id)
    by = {"GREEN": 0, "AMBER": 0, "RED": 0}
    for d, c in db.execute(q.group_by(ClearanceDecision.decision)).all():
        by[d] = c
    qs = select(WeighingEvent.source, func.count())
    if station_id:
        qs = qs.where(WeighingEvent.station_id == station_id)
    by_source = {s: c for s, c in db.execute(qs.group_by(WeighingEvent.source)).all()}
    lat = db.execute(select(func.avg(ClearanceDecision.latency_ms))).scalar() or 0.0
    total = sum(by.values())
    return StatsOut(total=total, by_decision=by, by_source=by_source, mean_latency_ms=float(lat), green_rate=(by["GREEN"] / total) if total else 0.0, stops_avoided=by["GREEN"])


class EdgeIngestIn(BaseModel):
    """Payload posted by a station gateway (or received over MQTT and forwarded by the ingest worker)."""

    device_id: str
    edge_event_id: str = Field(min_length=26, max_length=26)
    occurred_at: datetime
    measurement: dict
    anpr_plate: str | None = None
    anpr_confidence: float | None = Field(default=None, ge=0, le=1)
    rfid_epc: str | None = None
    rfid_confidence: float | None = Field(default=None, ge=0, le=1)
    raw_ref: str | None = None
    ambient_temp_c: float | None = None


@router.post("/ingest", response_model=WeighingOut, status_code=201)
def ingest(body: EdgeIngestIn, db: DbDep, p: Principal = Depends(require_roles("platform_admin", "weighbridge_operator"))):
    """Live measurements from an edge gateway. In the cloud the gateway authenticates with an mTLS device certificate at
    IoT Core and the ingest worker calls this with a service token; locally an operator token is accepted."""
    lane = db.execute(select(Lane).where(Lane.device_id == body.device_id)).scalar_one_or_none()
    if lane is None:
        raise HTTPException(404, f"No lane registered for device {body.device_id}")
    ev = process_lane_pass(db, lane, body.measurement, body.anpr_plate, body.anpr_confidence, body.rfid_epc, body.rfid_confidence,
                           occurred_at=body.occurred_at, source="live", edge_event_id=body.edge_event_id, raw_ref=body.raw_ref,
                           ambient_temp_c=body.ambient_temp_c)
    db.commit()
    return _out(db, ev)


class SimulateIn(BaseModel):
    lane_id: str
    count: int = Field(default=1, ge=1, le=50)
    overload_prob: float = Field(default=0.15, ge=0, le=1)
    sensor_fault_prob: float = Field(default=0.03, ge=0, le=1)
    anpr_misread_prob: float = Field(default=0.05, ge=0, le=1)
    rfid_missing_prob: float = Field(default=0.10, ge=0, le=1)
    clone_prob: float = Field(default=0.01, ge=0, le=1)
    unregistered_prob: float = Field(default=0.05, ge=0, le=1)
    pavement_temp_c: float = Field(default=32.0, ge=-10, le=80)
    vehicle_id: str | None = None
    force_gvm_kg: int | None = Field(default=None, ge=1000, le=90000)
    seed: int | None = None


@router.post("/simulate", response_model=list[WeighingOut], status_code=201)
def simulate(body: SimulateIn, db: DbDep, p: Principal = Depends(OPS)):
    """Generates synthetic lane passes through the full pipeline. Output is tagged source=simulated everywhere."""
    lane = db.get(Lane, body.lane_id)
    if lane is None:
        raise HTTPException(404, "Lane not found")
    out = []
    for i in range(body.count):
        opts = SimOptions(overload_prob=body.overload_prob, sensor_fault_prob=body.sensor_fault_prob, anpr_misread_prob=body.anpr_misread_prob,
                          rfid_missing_prob=body.rfid_missing_prob, clone_prob=body.clone_prob, unregistered_prob=body.unregistered_prob,
                          pavement_temp_c=body.pavement_temp_c, vehicle_id=body.vehicle_id, force_gvm_kg=body.force_gvm_kg,
                          seed=None if body.seed is None else body.seed + i)
        ev = simulate_pass(db, lane, opts)
        db.commit()
        out.append(_out(db, ev))
    return out


class StaticVerifyIn(BaseModel):
    static_gvm_kg: int = Field(ge=500, le=90000)
    axle_loads_kg: list[int] | None = None
    notes: str | None = None


@router.post("/events/{event_id}/static-verify", response_model=WeighingOut)
def static_verify(event_id: str, body: StaticVerifyIn, db: DbDep, p: Principal = Depends(require_roles("platform_admin", "weighbridge_operator"))):
    """Record the static-scale result for an AMBER/RED pass. The static scale is the legal reference; this issues the
    `static_certified` ticket and records the WIM-vs-static error for accuracy benchmarking."""
    ev = db.get(WeighingEvent, event_id)
    if ev is None or ev.decision is None:
        raise HTTPException(404, "Not found")
    d = ev.decision
    d.static_verified_gvm_kg = body.static_gvm_kg
    plate = db.get(Vehicle, ev.vehicle_id).plate if ev.vehicle_id else (ev.identity.anpr_plate if ev.identity else None)
    lane = db.get(Lane, ev.lane_id)
    station_code = lane.station.code if lane and lane.station else ev.station_id
    if d.ticket:
        db.delete(d.ticket)
        db.flush()
        db.refresh(d)
    t = tickets.issue(db, ev, d, "static_certified", plate, station_code)
    err_pct = (ev.gvm_kg - body.static_gvm_kg) / body.static_gvm_kg * 100.0
    ledger.append(db, "static.verified", {"weighing_event_id": ev.id, "static_gvm_kg": body.static_gvm_kg, "wim_gvm_kg": ev.gvm_kg,
                                           "wim_error_pct": round(err_pct, 2), "ticket_id": t.id, "operator": p.user.id}, station_id=ev.station_id, producer="static-scale")
    audit(db, p, "static_verify", "weighing_event", ev.id, after=body.model_dump())
    publish(EventType.TRUCK_RELEASED if body.static_gvm_kg <= DEFAULT_LIMITS.gvm_max_kg else EventType.TRUCK_DIVERTED,
            {"weighing_event_id": ev.id, "static_gvm_kg": body.static_gvm_kg, "wim_error_pct": round(err_pct, 2)}, station_id=ev.station_id)
    db.commit()
    db.refresh(ev)
    db.refresh(d)
    return _out(db, ev)


class OverrideIn(BaseModel):
    reason: str = Field(min_length=10, max_length=300)


@router.post("/events/{event_id}/override-release", response_model=WeighingOut)
def override_release(event_id: str, body: OverrideIn, db: DbDep, p: Principal = Depends(require_roles("platform_admin", "weighbridge_operator", mfa=True))):
    """Operator override (requires MFA). Only allowed when a static verification exists; the original decision is never deleted."""
    ev = db.get(WeighingEvent, event_id)
    if ev is None or ev.decision is None:
        raise HTTPException(404, "Not found")
    d = ev.decision
    if d.static_verified_gvm_kg is None:
        raise HTTPException(409, "Override requires a static verification record first")
    d.overridden_by, d.override_reason = p.user.id, body.reason
    ledger.append(db, "clearance.overridden", {"decision_id": d.id, "by": p.user.id, "reason": body.reason}, station_id=ev.station_id, producer="operator")
    audit(db, p, "override", "clearance_decision", d.id, after=body.model_dump())
    db.commit()
    return _out(db, ev)


@router.get("/limits")
def limits():
    lim = DEFAULT_LIMITS
    s = get_settings()
    return {"version": lim.version, "steering_single_kg": lim.steering_single_kg, "single_drive_kg": lim.single_drive_kg, "tandem_kg": lim.tandem_kg,
            "tridem_kg": lim.tridem_kg, "gvm_max_kg": lim.gvm_max_kg, "axle_tolerance_pct": lim.axle_tolerance_pct, "gvm_tolerance_pct": lim.gvm_tolerance_pct,
            "green_safety_margin_kg": lim.green_safety_margin_kg, "identity_min_confidence": s.identity_min_confidence,
            "audit_sample_rate": s.audit_sample_rate, "notes": lim.notes}
