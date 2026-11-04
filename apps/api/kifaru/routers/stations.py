from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from ..deps import CurrentUser, DbDep, Principal, audit, require_roles
from ..events import EventType, publish
from ..models import (
    SENSOR_KINDS,
    CalibrationRecord,
    ClearanceDecision,
    Incident,
    Lane,
    QueueRecord,
    Sensor,
    WeighingEvent,
    WeighingStation,
    utcnow,
)

router = APIRouter(prefix="/stations", tags=["stations"])
ADMIN = require_roles("platform_admin")
OPS = require_roles("platform_admin", "weighbridge_operator", "port_controller")

DEFAULT_LANE_SENSORS = [
    ("inductive_loop", 0.0), ("piezo_quartz", 4.0), ("piezo_quartz", 7.0), ("bending_plate", 10.0), ("inductive_loop", 12.0),
    ("piezo_quartz", 16.0), ("inductive_loop", 19.0), ("ir_beam", 4.0), ("radar_speed", -15.0), ("anpr_camera", -25.0),
    ("rfid_reader", -15.0), ("pavement_temp", 7.0), ("ambient_temp_rh", 30.0),
]
LOAD_SENSOR_KINDS = ("piezo_quartz", "piezo_polymer", "bending_plate", "strain_gauge")


class SensorOut(BaseModel):
    id: str
    kind: str
    serial: str | None
    channel: int | None
    install_position_m: float | None
    status: str
    health_reason: str | None
    last_reading_at: datetime | None
    calibration_valid_to: datetime | None


class LaneOut(BaseModel):
    id: str
    lane_no: int
    type: str
    direction: str
    status: str
    device_id: str | None
    calibration_valid_to: datetime | None
    sensors: list[SensorOut]


class StationOut(BaseModel):
    id: str
    code: str
    name: str
    lat: float
    lon: float
    capacity_per_hour: int
    static_capacity_per_hour: int
    alt_allowed: bool
    status: str
    lanes: list[LaneOut]
    queue_len: int
    avg_wait_s: int
    utilisation: float
    decisions_last_hour: dict[str, int]


def _aware(dt: datetime | None) -> datetime | None:
    """SQLite returns naive datetimes; normalise so comparisons never mix naive and aware values."""
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _sensor_out(s: Sensor) -> SensorOut:
    latest = max((_aware(c.valid_to) for c in s.calibrations), default=None)
    return SensorOut(id=s.id, kind=s.kind, serial=s.serial, channel=s.channel, install_position_m=s.install_position_m, status=s.status,
                     health_reason=s.health_reason, last_reading_at=s.last_reading_at, calibration_valid_to=latest)


def _lane_out(ln: Lane) -> LaneOut:
    return LaneOut(id=ln.id, lane_no=ln.lane_no, type=ln.type, direction=ln.direction, status=ln.status, device_id=ln.device_id,
                   calibration_valid_to=ln.calibration_valid_to, sensors=[_sensor_out(s) for s in ln.sensors])


def _station_out(db, st: WeighingStation) -> StationOut:
    q = db.execute(select(QueueRecord).where(QueueRecord.station_id == st.id, QueueRecord.kind == "observed").order_by(QueueRecord.ts.desc()).limit(1)).scalar_one_or_none()
    since = utcnow() - timedelta(hours=1)
    rows = db.execute(
        select(ClearanceDecision.decision, func.count()).join(WeighingEvent, WeighingEvent.id == ClearanceDecision.weighing_event_id)
        .where(WeighingEvent.station_id == st.id, ClearanceDecision.decided_at >= since).group_by(ClearanceDecision.decision)
    ).all()
    counts = {"GREEN": 0, "AMBER": 0, "RED": 0}
    for d, c in rows:
        counts[d] = c
    return StationOut(id=st.id, code=st.code, name=st.name, lat=st.lat, lon=st.lon, capacity_per_hour=st.capacity_per_hour,
                      static_capacity_per_hour=st.static_capacity_per_hour, alt_allowed=st.alt_allowed, status=st.status,
                      lanes=[_lane_out(ln) for ln in st.lanes], queue_len=q.queue_len if q else 0, avg_wait_s=q.avg_wait_s if q else 0,
                      utilisation=q.utilisation if q else 0.0, decisions_last_hour=counts)


@router.get("", response_model=list[StationOut])
def list_stations(p: CurrentUser, db: DbDep):
    return [_station_out(db, s) for s in db.execute(select(WeighingStation).order_by(WeighingStation.code)).scalars()]


@router.get("/{station_id}", response_model=StationOut)
def get_station(station_id: str, p: CurrentUser, db: DbDep):
    st = db.get(WeighingStation, station_id)
    if st is None:
        raise HTTPException(404, "Station not found")
    return _station_out(db, st)


class StationIn(BaseModel):
    code: str = Field(min_length=2, max_length=16)
    name: str
    lat: float
    lon: float
    capacity_per_hour: int = 120
    static_capacity_per_hour: int = 40
    alt_allowed: bool = False


@router.post("", response_model=StationOut, status_code=201)
def create_station(body: StationIn, db: DbDep, p: Principal = Depends(ADMIN)):
    st = WeighingStation(**body.model_dump())
    db.add(st)
    db.flush()
    audit(db, p, "create", "station", st.id, after=body.model_dump())
    db.commit()
    return _station_out(db, st)


class StationStatusIn(BaseModel):
    status: str = Field(pattern="^(operational|degraded|offline)$")
    reason: str | None = None


@router.post("/{station_id}/status", response_model=StationOut)
def set_station_status(station_id: str, body: StationStatusIn, db: DbDep, p: Principal = Depends(OPS)):
    st = db.get(WeighingStation, station_id)
    if st is None:
        raise HTTPException(404, "Station not found")
    audit(db, p, "status", "station", st.id, before={"status": st.status}, after=body.model_dump())
    st.status = body.status
    if body.status != "operational":
        inc = Incident(station_id=st.id, severity="high" if body.status == "offline" else "medium", category="station_failure",
                       title=f"Station {st.code} {body.status}", details={"reason": body.reason}, opened_at=utcnow(), raised_by=p.user.email)
        db.add(inc)
        db.flush()
        publish(EventType.STATION_FAILURE, {"station_id": st.id, "code": st.code, "status": body.status, "reason": body.reason, "incident_id": inc.id}, station_id=st.id)
    db.commit()
    return _station_out(db, st)


class LaneIn(BaseModel):
    lane_no: int = Field(ge=1, le=20)
    type: str = Field(default="wim_highspeed", pattern="^(wim_highspeed|wim_lowspeed|static)$")
    direction: str = "inbound"
    device_id: str | None = None


@router.post("/{station_id}/lanes", response_model=LaneOut, status_code=201)
def create_lane(station_id: str, body: LaneIn, db: DbDep, p: Principal = Depends(ADMIN)):
    if db.get(WeighingStation, station_id) is None:
        raise HTTPException(404, "Station not found")
    lane = Lane(station_id=station_id, **body.model_dump())
    db.add(lane)
    db.flush()
    if body.type != "static":
        for i, (kind, pos) in enumerate(DEFAULT_LANE_SENSORS):
            db.add(Sensor(lane_id=lane.id, kind=kind, channel=i, install_position_m=pos))
    audit(db, p, "create", "lane", lane.id)
    db.commit()
    db.refresh(lane)
    return _lane_out(lane)


class SensorHealthIn(BaseModel):
    status: str = Field(pattern="^(ok|degraded|fault)$")
    reason: str | None = None


@router.post("/sensors/{sensor_id}/health", response_model=SensorOut)
def set_sensor_health(sensor_id: str, body: SensorHealthIn, db: DbDep, p: Principal = Depends(OPS)):
    s = db.get(Sensor, sensor_id)
    if s is None:
        raise HTTPException(404, "Sensor not found")
    s.status, s.health_reason, s.last_reading_at = body.status, body.reason, utcnow()
    lane = s.lane
    if body.status == "fault" and lane.status == "operational":
        lane.status = "degraded"
    elif body.status == "ok" and all(x.status == "ok" for x in lane.sensors):
        lane.status = "operational"
    publish(EventType.SENSOR_HEALTH, {"sensor_id": s.id, "lane_id": lane.id, "kind": s.kind, "status": body.status, "reason": body.reason}, station_id=lane.station_id)
    db.commit()
    return _sensor_out(s)


class CalibrationIn(BaseModel):
    method: str = Field(pattern="^(reference_vehicle|static_scale_comparison|shunt|bench)$")
    reference_mass_kg: int | None = None
    gain: float = 1.0
    offset: float = 0.0
    temp_coeff_per_c: float = 0.0
    reference_temp_c: float = 25.0
    uncertainty_pct: float = Field(default=5.0, ge=0.1, le=50)
    valid_days: int = Field(default=180, ge=1, le=730)
    notes: str | None = None


class CalibrationOut(CalibrationIn):
    id: str
    sensor_id: str
    valid_from: datetime
    valid_to: datetime


def _recompute_lane_validity(lane: Lane) -> None:
    valids = []
    for x in lane.sensors:
        if x.kind in LOAD_SENSOR_KINDS:
            valids.append(max((_aware(c.valid_to) for c in x.calibrations), default=None))
    lane.calibration_valid_to = min(valids) if valids and all(v is not None for v in valids) else None


@router.post("/sensors/{sensor_id}/calibrations", response_model=CalibrationOut, status_code=201)
def add_calibration(sensor_id: str, body: CalibrationIn, db: DbDep, p: Principal = Depends(require_roles("platform_admin", "weighbridge_operator"))):
    s = db.get(Sensor, sensor_id)
    if s is None:
        raise HTTPException(404, "Sensor not found")
    now = utcnow()
    rec = CalibrationRecord(sensor_id=s.id, method=body.method, reference_mass_kg=body.reference_mass_kg, gain=body.gain, offset=body.offset,
                            temp_coeff_per_c=body.temp_coeff_per_c, reference_temp_c=body.reference_temp_c, uncertainty_pct=body.uncertainty_pct,
                            valid_from=now, valid_to=now + timedelta(days=body.valid_days), performed_by=p.user.id, notes=body.notes)
    db.add(rec)
    db.flush()
    db.refresh(s)
    _recompute_lane_validity(s.lane)
    audit(db, p, "calibrate", "sensor", s.id, after=body.model_dump())
    db.commit()
    return CalibrationOut(id=rec.id, sensor_id=s.id, valid_from=rec.valid_from, valid_to=rec.valid_to, **body.model_dump())


@router.get("/sensors/{sensor_id}/calibrations", response_model=list[CalibrationOut])
def list_calibrations(sensor_id: str, p: CurrentUser, db: DbDep):
    rows = db.execute(select(CalibrationRecord).where(CalibrationRecord.sensor_id == sensor_id).order_by(CalibrationRecord.valid_from.desc())).scalars()
    return [CalibrationOut(id=r.id, sensor_id=r.sensor_id, method=r.method, reference_mass_kg=r.reference_mass_kg, gain=r.gain, offset=r.offset,
                           temp_coeff_per_c=r.temp_coeff_per_c, reference_temp_c=r.reference_temp_c, uncertainty_pct=r.uncertainty_pct,
                           valid_days=(r.valid_to - r.valid_from).days, notes=r.notes, valid_from=r.valid_from, valid_to=r.valid_to) for r in rows]


@router.get("/meta/sensor-kinds")
def sensor_kinds():
    return SENSOR_KINDS
