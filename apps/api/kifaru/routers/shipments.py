"""Shipments and the Digital Cargo Passport (Module 5, Module 7 backend)."""
from __future__ import annotations

import secrets
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select

from ..deps import CurrentUser, DbDep, Principal, audit, org_scope, require_roles
from ..events import EventType, publish
from ..models import (
    SHIPMENT_STAGES,
    CargoDeclaration,
    CargoProcessingEvent,
    Container,
    DeliveryRecord,
    DigitalTicket,
    ElectronicSeal,
    Organization,
    Shipment,
    Vehicle,
    Warehouse,
    WeighingEvent,
    utcnow,
)
from ..services import ledger
from .notifications import notify

router = APIRouter(prefix="/shipments", tags=["shipments"])
OWNER_WRITE = require_roles("cargo_owner", "transporter_admin", "dispatcher", "platform_admin")
STAGE_WRITE = require_roles("platform_admin", "port_controller", "weighbridge_operator", "warehouse_manager", "transporter_admin", "dispatcher")


def iso6346_check_digit(number: str) -> int:
    """ISO 6346 container number check digit."""
    letter_values = {}
    v = 10
    for ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        if v % 11 == 0:
            v += 1
        letter_values[ch] = v
        v += 1
    total = 0
    for i, ch in enumerate(number[:10]):
        val = letter_values[ch] if ch.isalpha() else int(ch)
        total += val * (2**i)
    return (total % 11) % 10


class ContainerIn(BaseModel):
    number: str = Field(min_length=11, max_length=11)
    size_ft: int = Field(default=40, ge=10, le=53)
    type: str = "GP"

    @field_validator("number")
    @classmethod
    def _check(cls, v: str) -> str:
        v = v.upper()
        if not (v[:4].isalpha() and v[4:].isdigit()):
            raise ValueError("container number must be 4 letters + 7 digits")
        if iso6346_check_digit(v) != int(v[10]):
            raise ValueError("ISO 6346 check digit invalid")
        return v


class ShipmentIn(BaseModel):
    description: str = Field(min_length=3, max_length=300)
    cargo_type: str = Field(default="general", pattern="^(general|container|bulk|liquid|reefer|hazardous)$")
    origin: str
    destination: str
    origin_lat: float | None = None
    origin_lon: float | None = None
    dest_lat: float | None = None
    dest_lon: float | None = None
    declared_mass_kg: int = Field(ge=0, le=60000)
    vgm_kg: int | None = Field(default=None, ge=0, le=60000)
    transporter_org_id: str | None = None
    vehicle_id: str | None = None
    warehouse_id: str | None = None
    containers: list[ContainerIn] = []
    declaration_reference: str | None = None
    seal_id: str | None = None


class ProcessingEventOut(BaseModel):
    id: str
    stage: str
    status: str
    occurred_at: datetime
    source: str
    notes: str | None


class PassportOut(BaseModel):
    id: str
    reference: str
    owner_org_id: str
    owner_org_name: str | None
    transporter_org_id: str | None
    transporter_org_name: str | None
    vehicle_id: str | None
    vehicle_plate: str | None
    vehicle_rfid: list[str]
    trailer_id: str | None
    warehouse_id: str | None
    description: str
    cargo_type: str
    origin: str
    destination: str
    origin_lat: float | None
    origin_lon: float | None
    dest_lat: float | None
    dest_lon: float | None
    declared_mass_kg: int
    vgm_kg: int | None
    stage: str
    status: str
    containers: list[dict]
    declaration: dict | None
    seals: list[dict]
    processing_events: list[ProcessingEventOut]
    weighings: list[dict]
    tickets: list[dict]
    predicted_release_at: datetime | None
    predicted_release_p10: datetime | None
    predicted_release_p90: datetime | None
    prediction_explanation: dict | None
    outstanding: list[str]
    created_at: datetime


def _passport(db, s: Shipment) -> PassportOut:
    owner = db.get(Organization, s.owner_org_id)
    tr = db.get(Organization, s.transporter_org_id) if s.transporter_org_id else None
    v = db.get(Vehicle, s.vehicle_id) if s.vehicle_id else None
    weighings = db.execute(select(WeighingEvent).where(WeighingEvent.shipment_id == s.id).order_by(WeighingEvent.occurred_at)).scalars().all()
    tix = []
    for w in weighings:
        if w.decision and w.decision.ticket:
            t: DigitalTicket = w.decision.ticket
            tix.append({"id": t.id, "type": t.type, "qr_token": t.qr_token, "decision": w.decision.decision, "gvm_kg": w.gvm_kg, "source": w.source})
    idx = SHIPMENT_STAGES.index(s.stage) if s.stage in SHIPMENT_STAGES else 0
    outstanding = [st for st in SHIPMENT_STAGES[idx + 1 :] if st not in ("closed",)]
    if s.declaration is None:
        outstanding.insert(0, "cargo declaration missing")
    if s.vehicle_id is None:
        outstanding.insert(0, "truck not assigned")
    return PassportOut(
        id=s.id, reference=s.reference, owner_org_id=s.owner_org_id, owner_org_name=owner.name if owner else None,
        transporter_org_id=s.transporter_org_id, transporter_org_name=tr.name if tr else None, vehicle_id=s.vehicle_id,
        vehicle_plate=v.plate if v else None, vehicle_rfid=[t.epc for t in v.tags] if v else [], trailer_id=s.trailer_id,
        warehouse_id=s.warehouse_id, description=s.description, cargo_type=s.cargo_type, origin=s.origin, destination=s.destination,
        origin_lat=s.origin_lat, origin_lon=s.origin_lon, dest_lat=s.dest_lat, dest_lon=s.dest_lon, declared_mass_kg=s.declared_mass_kg,
        vgm_kg=s.vgm_kg, stage=s.stage, status=s.status,
        containers=[{"id": c.id, "number": c.number, "size_ft": c.size_ft, "type": c.type} for c in s.containers],
        declaration={"id": s.declaration.id, "reference": s.declaration.reference, "source": s.declaration.source, "status": s.declaration.status,
                     "declared_mass_kg": s.declaration.declared_mass_kg} if s.declaration else None,
        seals=[{"id": e.id, "seal_id": e.seal_id, "provider": e.provider, "status": e.status, "armed_at": e.armed_at, "breached_at": e.breached_at} for e in s.seals],
        processing_events=[ProcessingEventOut(id=e.id, stage=e.stage, status=e.status, occurred_at=e.occurred_at, source=e.source, notes=e.notes) for e in s.processing_events],
        weighings=[{"id": w.id, "occurred_at": w.occurred_at, "gvm_kg": w.gvm_kg, "u_kg": w.gvm_uncertainty_kg, "decision": w.decision.decision if w.decision else None,
                    "station_id": w.station_id, "source": w.source} for w in weighings],
        tickets=tix, predicted_release_at=s.predicted_release_at, predicted_release_p10=s.predicted_release_p10, predicted_release_p90=s.predicted_release_p90,
        prediction_explanation=s.prediction_explanation, outstanding=outstanding, created_at=s.created_at,
    )


def _visible(p, s: Shipment) -> bool:
    scope = org_scope(p)
    return scope is None or s.owner_org_id == scope or s.transporter_org_id == scope or (
        s.warehouse_id is not None and p.has_role("warehouse_manager")
    )


@router.get("", response_model=list[PassportOut])
def list_shipments(p: CurrentUser, db: DbDep, stage: str | None = None, warehouse_id: str | None = None):
    q = select(Shipment).order_by(Shipment.created_at.desc())
    if stage:
        q = q.where(Shipment.stage == stage)
    if warehouse_id:
        q = q.where(Shipment.warehouse_id == warehouse_id)
    return [_passport(db, s) for s in db.execute(q).scalars() if _visible(p, s)]


@router.post("", response_model=PassportOut, status_code=201)
def create_shipment(body: ShipmentIn, db: DbDep, p: Principal = Depends(OWNER_WRITE)):
    if not p.org_id:
        raise HTTPException(400, "User has no organisation")
    ref = "KP-" + secrets.token_hex(4).upper()
    s = Shipment(reference=ref, owner_org_id=p.org_id, transporter_org_id=body.transporter_org_id, vehicle_id=body.vehicle_id,
                 warehouse_id=body.warehouse_id, description=body.description, cargo_type=body.cargo_type, origin=body.origin,
                 destination=body.destination, origin_lat=body.origin_lat, origin_lon=body.origin_lon, dest_lat=body.dest_lat, dest_lon=body.dest_lon,
                 declared_mass_kg=body.declared_mass_kg, vgm_kg=body.vgm_kg)
    db.add(s)
    db.flush()
    for c in body.containers:
        db.add(Container(shipment_id=s.id, number=c.number, size_ft=c.size_ft, type=c.type))
    if body.declaration_reference:
        db.add(CargoDeclaration(shipment_id=s.id, reference=body.declaration_reference, source="manual", declared_mass_kg=body.declared_mass_kg))
        s.stage = "declared"
    if body.seal_id:
        db.add(ElectronicSeal(shipment_id=s.id, seal_id=body.seal_id, provider="mock", status="armed", armed_at=utcnow()))
    db.add(CargoProcessingEvent(shipment_id=s.id, stage="registered", occurred_at=utcnow(), source="platform", actor_user_id=p.user.id))
    ledger.append(db, "shipment.registered", {"shipment_id": s.id, "reference": ref, "owner_org_id": p.org_id, "declared_mass_kg": body.declared_mass_kg}, producer="cargo-passport")
    audit(db, p, "create", "shipment", s.id, after={"reference": ref})
    db.commit()
    db.refresh(s)
    publish(EventType.CARGO_STATUS_CHANGED, {"shipment_id": s.id, "reference": ref, "stage": s.stage}, org_id=p.org_id)
    return _passport(db, s)


@router.get("/{shipment_id}", response_model=PassportOut)
def get_shipment(shipment_id: str, p: CurrentUser, db: DbDep):
    s = db.get(Shipment, shipment_id)
    if s is None and len(shipment_id) < 26:
        s = db.execute(select(Shipment).where(Shipment.reference == shipment_id.upper())).scalar_one_or_none()
    if s is None or not _visible(p, s):
        raise HTTPException(404, "Shipment not found")
    return _passport(db, s)


class StageIn(BaseModel):
    stage: str
    status: str = Field(default="completed", pattern="^(started|completed|blocked)$")
    notes: str | None = None

    @field_validator("stage")
    @classmethod
    def _stage(cls, v: str) -> str:
        if v not in SHIPMENT_STAGES:
            raise ValueError(f"stage must be one of {SHIPMENT_STAGES}")
        return v


@router.post("/{shipment_id}/stage", response_model=PassportOut)
def advance_stage(shipment_id: str, body: StageIn, db: DbDep, p: Principal = Depends(STAGE_WRITE)):
    s = db.get(Shipment, shipment_id)
    if s is None or not _visible(p, s):
        raise HTTPException(404, "Shipment not found")
    before = s.stage
    db.add(CargoProcessingEvent(shipment_id=s.id, stage=body.stage, status=body.status, occurred_at=utcnow(), source="manual", notes=body.notes, actor_user_id=p.user.id))
    if body.status == "completed":
        s.stage = body.stage
    if body.stage == "delivered" and body.status == "completed":
        db.add(DeliveryRecord(shipment_id=s.id, delivered_at=utcnow(), notes=body.notes))
        publish(EventType.SHIPMENT_DELIVERED, {"shipment_id": s.id, "reference": s.reference}, org_id=s.owner_org_id)
    ledger.append(db, "cargo.status_changed", {"shipment_id": s.id, "from": before, "to": body.stage, "status": body.status, "by": p.user.id}, producer="cargo-passport")
    audit(db, p, "stage", "shipment", s.id, before={"stage": before}, after=body.model_dump())
    notify(db, user_id=None, org_id=s.owner_org_id, template="cargo_stage", title=f"Shipment {s.reference}: {body.stage} {body.status}",
           body=f"Shipment {s.reference} is now {body.stage} ({body.status}).", payload={"shipment_id": s.id, "stage": body.stage, "status": body.status})
    db.commit()
    db.refresh(s)
    publish(EventType.CARGO_STATUS_CHANGED, {"shipment_id": s.id, "reference": s.reference, "stage": s.stage, "status": body.status}, org_id=s.owner_org_id)
    if body.stage == "weighing_verification" and body.status == "completed":
        publish(EventType.CARGO_VERIFIED, {"shipment_id": s.id, "reference": s.reference}, org_id=s.owner_org_id)
    return _passport(db, s)


@router.post("/{shipment_id}/predict-release", response_model=PassportOut)
def predict_release(shipment_id: str, p: CurrentUser, db: DbDep):
    """Runs the Predictive Release Agent (advisory) and stores P10/P50/P90 plus reasons on the passport."""
    s = db.get(Shipment, shipment_id)
    if s is None or not _visible(p, s):
        raise HTTPException(404, "Shipment not found")
    from ..workers.jobs import refresh_release_predictions

    refresh_release_predictions(db)
    db.commit()
    db.refresh(s)
    return _passport(db, s)


class AssignIn(BaseModel):
    vehicle_id: str
    transporter_org_id: str | None = None
    driver_id: str | None = None


@router.post("/{shipment_id}/assign", response_model=PassportOut)
def assign_truck(shipment_id: str, body: AssignIn, db: DbDep, p: Principal = Depends(OWNER_WRITE)):
    s = db.get(Shipment, shipment_id)
    if s is None or not _visible(p, s):
        raise HTTPException(404, "Shipment not found")
    v = db.get(Vehicle, body.vehicle_id)
    if v is None:
        raise HTTPException(404, "Vehicle not found")
    s.vehicle_id, s.transporter_org_id, s.driver_id = v.id, body.transporter_org_id or v.org_id, body.driver_id
    ledger.append(db, "shipment.assigned", {"shipment_id": s.id, "vehicle_id": v.id, "plate": v.plate}, producer="cargo-passport")
    audit(db, p, "assign", "shipment", s.id, after=body.model_dump())
    db.commit()
    db.refresh(s)
    return _passport(db, s)


class SealIn(BaseModel):
    seal_id: str
    status: str = Field(pattern="^(armed|breached|removed|unknown)$")


@router.post("/{shipment_id}/seal", response_model=PassportOut)
def seal_update(shipment_id: str, body: SealIn, db: DbDep, p: Principal = Depends(STAGE_WRITE)):
    s = db.get(Shipment, shipment_id)
    if s is None:
        raise HTTPException(404, "Shipment not found")
    seal = next((e for e in s.seals if e.seal_id == body.seal_id), None)
    if seal is None:
        seal = ElectronicSeal(shipment_id=s.id, seal_id=body.seal_id, provider="mock")
        db.add(seal)
    seal.status = body.status
    if body.status == "armed":
        seal.armed_at = utcnow()
    if body.status == "breached":
        seal.breached_at = utcnow()
    ledger.append(db, "seal.status", {"shipment_id": s.id, "seal_id": body.seal_id, "status": body.status}, producer="seal-adapter")
    db.commit()
    db.refresh(s)
    return _passport(db, s)


# ----------------------------------------------------------------- warehouses
class WarehouseIn(BaseModel):
    name: str
    lat: float
    lon: float
    dock_count: int = 2


class WarehouseOut(WarehouseIn):
    id: str
    org_id: str
    readiness_status: str
    incoming: int


@router.get("/warehouses/all", response_model=list[WarehouseOut])
def list_warehouses(p: CurrentUser, db: DbDep):
    out = []
    for w in db.execute(select(Warehouse)).scalars():
        n = len(db.execute(select(Shipment.id).where(Shipment.warehouse_id == w.id, Shipment.stage.notin_(["delivered", "closed"]))).all())
        out.append(WarehouseOut(id=w.id, org_id=w.org_id, name=w.name, lat=w.lat, lon=w.lon, dock_count=w.dock_count, readiness_status=w.readiness_status, incoming=n))
    return out


@router.post("/warehouses", response_model=WarehouseOut, status_code=201)
def create_warehouse(body: WarehouseIn, db: DbDep, p: Principal = Depends(require_roles("warehouse_manager", "platform_admin"))):
    w = Warehouse(org_id=p.org_id, **body.model_dump())
    db.add(w)
    db.commit()
    return WarehouseOut(id=w.id, org_id=w.org_id, readiness_status=w.readiness_status, incoming=0, **body.model_dump())


class ReadinessIn(BaseModel):
    readiness_status: str = Field(pattern="^(ready|busy|closed)$")


@router.post("/warehouses/{warehouse_id}/readiness", response_model=WarehouseOut)
def set_readiness(warehouse_id: str, body: ReadinessIn, db: DbDep, p: Principal = Depends(require_roles("warehouse_manager", "platform_admin"))):
    w = db.get(Warehouse, warehouse_id)
    if w is None:
        raise HTTPException(404, "Warehouse not found")
    w.readiness_status = body.readiness_status
    db.commit()
    n = len(db.execute(select(Shipment.id).where(Shipment.warehouse_id == w.id, Shipment.stage.notin_(["delivered", "closed"]))).all())
    return WarehouseOut(id=w.id, org_id=w.org_id, name=w.name, lat=w.lat, lon=w.lon, dock_count=w.dock_count, readiness_status=w.readiness_status, incoming=n)
