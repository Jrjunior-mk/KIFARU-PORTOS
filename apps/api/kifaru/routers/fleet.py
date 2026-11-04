from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..deps import CurrentUser, DbDep, Principal, audit, org_scope, require_roles
from ..models import Driver, DriverPII, Fleet, Organization, RfidTag, Trailer, Vehicle, utcnow
from ..pii import encrypt
from ..services.identity import normalise_plate

router = APIRouter(prefix="/fleet", tags=["fleet"])

FLEET_WRITE = require_roles("transporter_admin", "dispatcher", "platform_admin")


class OrgOut(BaseModel):
    id: str
    name: str
    type: str
    status: str


@router.get("/orgs", response_model=list[OrgOut])
def list_orgs(p: CurrentUser, db: DbDep, type: str | None = None):
    q = select(Organization)
    scope = org_scope(p)
    if scope:
        q = q.where(Organization.id == scope)
    if type:
        q = q.where(Organization.type == type)
    return [OrgOut(id=o.id, name=o.name, type=o.type, status=o.status) for o in db.execute(q).scalars()]


class FleetIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)


class FleetOut(FleetIn):
    id: str
    org_id: str
    vehicle_count: int


@router.get("/fleets", response_model=list[FleetOut])
def list_fleets(p: CurrentUser, db: DbDep):
    q = select(Fleet)
    scope = org_scope(p)
    if scope:
        q = q.where(Fleet.org_id == scope)
    return [FleetOut(id=f.id, org_id=f.org_id, name=f.name, vehicle_count=len(f.vehicles)) for f in db.execute(q).scalars()]


@router.post("/fleets", response_model=FleetOut, status_code=201)
def create_fleet(body: FleetIn, db: DbDep, p: Principal = Depends(FLEET_WRITE)):
    if not p.org_id:
        raise HTTPException(400, "User has no organisation")
    f = Fleet(org_id=p.org_id, name=body.name)
    db.add(f)
    db.flush()
    audit(db, p, "create", "fleet", f.id, after={"name": f.name})
    db.commit()
    return FleetOut(id=f.id, org_id=f.org_id, name=f.name, vehicle_count=0)


class VehicleIn(BaseModel):
    plate: str = Field(min_length=5, max_length=16)
    fleet_id: str | None = None
    make: str | None = None
    model: str | None = None
    axle_config: str = Field(default="1+1", pattern=r"^\d(\+\d)*$")
    tare_kg: int = Field(ge=1000, le=30000)
    max_gvm_kg: int = Field(default=56000, ge=3500, le=56000)
    payload_capacity_kg: int = Field(default=28000, ge=0, le=50000)
    body_type: str = Field(default="flatbed", pattern="^(flatbed|container|tanker|box|tipper|reefer)$")
    rfid_epc: str | None = None


class VehicleOut(BaseModel):
    id: str
    org_id: str
    fleet_id: str | None
    plate: str
    make: str | None
    model: str | None
    axle_config: str
    class_code: str
    tare_kg: int
    max_gvm_kg: int
    payload_capacity_kg: int
    body_type: str
    status: str
    rfid_epcs: list[str]
    last_lat: float | None
    last_lon: float | None
    last_seen_at: datetime | None
    watchlisted: bool


def _v_out(v: Vehicle) -> VehicleOut:
    return VehicleOut(
        id=v.id, org_id=v.org_id, fleet_id=v.fleet_id, plate=v.plate, make=v.make, model=v.model, axle_config=v.axle_config,
        class_code=v.class_code, tare_kg=v.tare_kg, max_gvm_kg=v.max_gvm_kg, payload_capacity_kg=v.payload_capacity_kg,
        body_type=v.body_type, status=v.status, rfid_epcs=[t.epc for t in v.tags if t.revoked_at is None],
        last_lat=v.last_lat, last_lon=v.last_lon, last_seen_at=v.last_seen_at, watchlisted=bool(v.watchlist_reason),
    )


@router.get("/vehicles", response_model=list[VehicleOut])
def list_vehicles(p: CurrentUser, db: DbDep, org_id: str | None = None):
    q = select(Vehicle).order_by(Vehicle.plate)
    scope = org_scope(p)
    if scope:
        q = q.where(Vehicle.org_id == scope)
    elif org_id:
        q = q.where(Vehicle.org_id == org_id)
    return [_v_out(v) for v in db.execute(q).scalars()]


@router.post("/vehicles", response_model=VehicleOut, status_code=201)
def create_vehicle(body: VehicleIn, db: DbDep, p: Principal = Depends(FLEET_WRITE)):
    if not p.org_id:
        raise HTTPException(400, "User has no organisation")
    plate = body.plate.upper().strip()
    if db.execute(select(Vehicle).where(Vehicle.plate_norm == normalise_plate(plate))).scalars().first():
        raise HTTPException(409, "Plate already registered")
    v = Vehicle(
        org_id=p.org_id, fleet_id=body.fleet_id, plate=plate, plate_norm=normalise_plate(plate), make=body.make, model=body.model, axle_config=body.axle_config,
        class_code=f"HGV{sum(int(x) for x in body.axle_config.split('+'))}", tare_kg=body.tare_kg, max_gvm_kg=body.max_gvm_kg,
        payload_capacity_kg=body.payload_capacity_kg, body_type=body.body_type,
    )
    db.add(v)
    db.flush()
    if body.rfid_epc:
        db.add(RfidTag(epc=body.rfid_epc.upper(), vehicle_id=v.id, issued_at=utcnow()))
    audit(db, p, "create", "vehicle", v.id, after={"plate": plate})
    db.commit()
    db.refresh(v)
    return _v_out(v)


@router.get("/vehicles/{vehicle_id}", response_model=VehicleOut)
def get_vehicle(vehicle_id: str, p: CurrentUser, db: DbDep):
    v = db.get(Vehicle, vehicle_id)
    if v is None or (org_scope(p) and v.org_id != org_scope(p)):
        raise HTTPException(404, "Vehicle not found")
    return _v_out(v)


class PositionIn(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


@router.post("/vehicles/{vehicle_id}/position", response_model=VehicleOut)
def update_position(vehicle_id: str, body: PositionIn, db: DbDep, p: Principal = Depends(require_roles("transporter_admin", "dispatcher", "driver", "platform_admin"))):
    """Telematics position update (from the driver app or a telematics adapter)."""
    v = db.get(Vehicle, vehicle_id)
    if v is None or (org_scope(p) and v.org_id != org_scope(p)):
        raise HTTPException(404, "Vehicle not found")
    v.last_lat, v.last_lon, v.last_seen_at = body.lat, body.lon, utcnow()
    db.commit()
    return _v_out(v)


class WatchlistIn(BaseModel):
    reason: str | None = Field(default=None, max_length=200)


@router.post("/vehicles/{vehicle_id}/watchlist", response_model=VehicleOut)
def set_watchlist(vehicle_id: str, body: WatchlistIn, db: DbDep, p: Principal = Depends(require_roles("platform_admin", "port_controller", "auditor"))):
    v = db.get(Vehicle, vehicle_id)
    if v is None:
        raise HTTPException(404, "Vehicle not found")
    audit(db, p, "watchlist", "vehicle", v.id, before={"reason": v.watchlist_reason}, after={"reason": body.reason})
    v.watchlist_reason = body.reason
    db.commit()
    return _v_out(v)


class TrailerIn(BaseModel):
    plate: str = Field(min_length=4, max_length=16)
    axle_config: str = Field(default="2", pattern=r"^\d(\+\d)*$")
    tare_kg: int = Field(ge=500, le=20000)


class TrailerOut(TrailerIn):
    id: str
    org_id: str
    status: str


@router.get("/trailers", response_model=list[TrailerOut])
def list_trailers(p: CurrentUser, db: DbDep):
    q = select(Trailer)
    if org_scope(p):
        q = q.where(Trailer.org_id == org_scope(p))
    return [TrailerOut(id=t.id, org_id=t.org_id, plate=t.plate, axle_config=t.axle_config, tare_kg=t.tare_kg, status=t.status) for t in db.execute(q).scalars()]


@router.post("/trailers", response_model=TrailerOut, status_code=201)
def create_trailer(body: TrailerIn, db: DbDep, p: Principal = Depends(FLEET_WRITE)):
    t = Trailer(org_id=p.org_id, plate=body.plate.upper(), axle_config=body.axle_config, tare_kg=body.tare_kg)
    db.add(t)
    db.commit()
    return TrailerOut(id=t.id, org_id=t.org_id, plate=t.plate, axle_config=t.axle_config, tare_kg=t.tare_kg, status=t.status)


class DriverIn(BaseModel):
    full_name: str = Field(min_length=2, max_length=200)
    phone: str | None = None
    license_class: str | None = Field(default=None, max_length=8)
    fleet_id: str | None = None


class DriverOut(BaseModel):
    id: str
    org_id: str
    full_name: str
    license_class: str | None
    status: str


@router.get("/drivers", response_model=list[DriverOut])
def list_drivers(p: CurrentUser, db: DbDep):
    q = select(Driver)
    if org_scope(p):
        q = q.where(Driver.org_id == org_scope(p))
    return [DriverOut(id=d.id, org_id=d.org_id, full_name=d.pii.full_name if d.pii else "", license_class=d.license_class, status=d.status) for d in db.execute(q).scalars()]


@router.post("/drivers", response_model=DriverOut, status_code=201)
def create_driver(body: DriverIn, db: DbDep, p: Principal = Depends(FLEET_WRITE)):
    d = Driver(org_id=p.org_id, fleet_id=body.fleet_id, license_class=body.license_class)
    db.add(d)
    db.flush()
    db.add(DriverPII(driver_id=d.id, full_name=body.full_name, phone_enc=encrypt(body.phone)))
    audit(db, p, "create", "driver", d.id)
    db.commit()
    return DriverOut(id=d.id, org_id=d.org_id, full_name=body.full_name, license_class=d.license_class, status=d.status)
