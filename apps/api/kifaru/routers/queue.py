"""Queue state, slot booking and forecasts (Module 3)."""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from ..deps import CurrentUser, DbDep, Principal, audit, org_scope, require_roles
from ..events import EventType, publish
from ..models import Appointment, QueueRecord, Vehicle, WeighingStation, utcnow
from ..services.queue_forecast import forecast_station, slot_capacity

router = APIRouter(prefix="/queue", tags=["queue"])
SLOT_WINDOW_MIN = 15


class QueueOut(BaseModel):
    station_id: str
    ts: datetime
    kind: str
    queue_len: int
    avg_wait_s: int
    utilisation: float
    arrivals_per_hour: float
    lower: int | None
    upper: int | None
    model_version: str | None
    source: str


def _q_out(r: QueueRecord) -> QueueOut:
    return QueueOut(station_id=r.station_id, ts=r.ts, kind=r.kind, queue_len=r.queue_len, avg_wait_s=r.avg_wait_s, utilisation=r.utilisation,
                    arrivals_per_hour=r.arrivals_per_hour, lower=r.lower, upper=r.upper, model_version=r.model_version, source=r.source)


@router.get("/{station_id}/history", response_model=list[QueueOut])
def history(station_id: str, p: CurrentUser, db: DbDep, hours: int = 24):
    since = utcnow() - timedelta(hours=hours)
    rows = db.execute(select(QueueRecord).where(QueueRecord.station_id == station_id, QueueRecord.kind == "observed", QueueRecord.ts >= since).order_by(QueueRecord.ts)).scalars()
    return [_q_out(r) for r in rows]


class ObservationIn(BaseModel):
    queue_len: int = Field(ge=0, le=2000)
    avg_wait_s: int = Field(ge=0, le=86400)
    arrivals_per_hour: float = Field(ge=0, le=2000)
    source: str = Field(default="simulated", pattern="^(live|simulated|replay)$")


@router.post("/{station_id}/observe", response_model=QueueOut, status_code=201)
def observe(station_id: str, body: ObservationIn, db: DbDep, p: Principal = Depends(require_roles("platform_admin", "port_controller", "weighbridge_operator"))):
    st = db.get(WeighingStation, station_id)
    if st is None:
        raise HTTPException(404, "Station not found")
    util = min(1.0, body.arrivals_per_hour / max(1, st.capacity_per_hour))
    r = QueueRecord(station_id=st.id, ts=utcnow(), kind="observed", queue_len=body.queue_len, avg_wait_s=body.avg_wait_s, utilisation=util,
                    arrivals_per_hour=body.arrivals_per_hour, source=body.source)
    db.add(r)
    db.commit()
    publish(EventType.QUEUE_UPDATED, {"station_id": st.id, "code": st.code, "queue_len": r.queue_len, "avg_wait_s": r.avg_wait_s, "utilisation": util, "source": body.source}, station_id=st.id)
    return _q_out(r)


@router.get("/{station_id}/forecast", response_model=list[QueueOut])
def forecast(station_id: str, p: CurrentUser, db: DbDep):
    """Forecasts queue length / wait at +15, +30, +60, +120 min. Uses the traffic-forecast agent on observed history."""
    st = db.get(WeighingStation, station_id)
    if st is None:
        raise HTTPException(404, "Station not found")
    hist = db.execute(select(QueueRecord).where(QueueRecord.station_id == st.id, QueueRecord.kind == "observed").order_by(QueueRecord.ts.desc()).limit(96)).scalars().all()
    recs = forecast_station(st, list(reversed(hist)))
    for r in recs:
        db.add(r)
    db.commit()
    return [_q_out(r) for r in recs]


# ----------------------------------------------------------------- appointments / slots
class SlotOut(BaseModel):
    slot_start: datetime
    slot_end: datetime
    capacity: int
    booked: int
    available: int


@router.get("/{station_id}/slots", response_model=list[SlotOut])
def slots(station_id: str, p: CurrentUser, db: DbDep, hours: int = 6):
    st = db.get(WeighingStation, station_id)
    if st is None:
        raise HTTPException(404, "Station not found")
    now = utcnow().replace(second=0, microsecond=0)
    start = now - timedelta(minutes=now.minute % SLOT_WINDOW_MIN)
    out = []
    cap = slot_capacity(st, SLOT_WINDOW_MIN)
    for i in range(hours * 60 // SLOT_WINDOW_MIN):
        s0 = start + timedelta(minutes=i * SLOT_WINDOW_MIN)
        s1 = s0 + timedelta(minutes=SLOT_WINDOW_MIN)
        booked = db.execute(select(func.count()).select_from(Appointment).where(Appointment.station_id == st.id, Appointment.slot_start == s0, Appointment.status.in_(["booked", "arrived"]))).scalar_one()
        out.append(SlotOut(slot_start=s0, slot_end=s1, capacity=cap, booked=booked, available=max(0, cap - booked)))
    return out


class BookIn(BaseModel):
    vehicle_id: str
    slot_start: datetime
    shipment_id: str | None = None
    priority: int = Field(default=5, ge=1, le=9)


class AppointmentOut(BaseModel):
    id: str
    station_id: str
    station_code: str
    vehicle_id: str
    plate: str
    shipment_id: str | None
    slot_start: datetime
    slot_end: datetime
    status: str
    priority: int
    est_wait_s: int | None
    assigned_by: str


def _a_out(db, a: Appointment) -> AppointmentOut:
    st = db.get(WeighingStation, a.station_id)
    v = db.get(Vehicle, a.vehicle_id)
    return AppointmentOut(id=a.id, station_id=a.station_id, station_code=st.code if st else "", vehicle_id=a.vehicle_id, plate=v.plate if v else "",
                          shipment_id=a.shipment_id, slot_start=a.slot_start, slot_end=a.slot_end, status=a.status, priority=a.priority,
                          est_wait_s=a.est_wait_s, assigned_by=a.assigned_by)


@router.post("/{station_id}/appointments", response_model=AppointmentOut, status_code=201)
def book(station_id: str, body: BookIn, db: DbDep, p: Principal = Depends(require_roles("transporter_admin", "dispatcher", "driver", "platform_admin", "port_controller"))):
    st = db.get(WeighingStation, station_id)
    if st is None:
        raise HTTPException(404, "Station not found")
    v = db.get(Vehicle, body.vehicle_id)
    if v is None or (org_scope(p) and v.org_id != org_scope(p)):
        raise HTTPException(404, "Vehicle not found")
    s0 = body.slot_start.replace(second=0, microsecond=0)
    if s0.minute % SLOT_WINDOW_MIN != 0:
        raise HTTPException(400, f"slot_start must align to {SLOT_WINDOW_MIN}-minute windows")
    cap = slot_capacity(st, SLOT_WINDOW_MIN)
    booked = db.execute(select(func.count()).select_from(Appointment).where(Appointment.station_id == st.id, Appointment.slot_start == s0, Appointment.status.in_(["booked", "arrived"]))).scalar_one()
    if booked >= cap:
        raise HTTPException(409, f"Slot full ({booked}/{cap}); choose another window")
    dup = db.execute(select(Appointment).where(Appointment.vehicle_id == v.id, Appointment.status == "booked", Appointment.slot_start >= utcnow() - timedelta(hours=1))).scalars().first()
    if dup:
        raise HTTPException(409, "Vehicle already has an active appointment")
    latest = db.execute(select(QueueRecord).where(QueueRecord.station_id == st.id, QueueRecord.kind == "observed").order_by(QueueRecord.ts.desc()).limit(1)).scalar_one_or_none()
    a = Appointment(station_id=st.id, vehicle_id=v.id, shipment_id=body.shipment_id, requested_by=p.user.id, slot_start=s0,
                    slot_end=s0 + timedelta(minutes=SLOT_WINDOW_MIN), priority=body.priority, est_wait_s=(latest.avg_wait_s if latest else 0))
    db.add(a)
    audit(db, p, "book", "appointment", None, after=body.model_dump(mode="json"))
    db.commit()
    publish(EventType.QUEUE_UPDATED, {"station_id": st.id, "appointment_id": a.id, "slot_start": s0.isoformat(), "plate": v.plate}, station_id=st.id, org_id=v.org_id)
    return _a_out(db, a)


@router.get("/appointments/mine", response_model=list[AppointmentOut])
def my_appointments(p: CurrentUser, db: DbDep, station_id: str | None = None):
    q = select(Appointment).order_by(Appointment.slot_start.desc()).limit(200)
    if station_id:
        q = q.where(Appointment.station_id == station_id)
    scope = org_scope(p)
    if scope:
        q = q.join(Vehicle, Vehicle.id == Appointment.vehicle_id).where(Vehicle.org_id == scope)
    return [_a_out(db, a) for a in db.execute(q).scalars()]


class ApptStatusIn(BaseModel):
    status: str = Field(pattern="^(arrived|completed|missed|cancelled)$")


@router.post("/appointments/{appointment_id}/status", response_model=AppointmentOut)
def appt_status(appointment_id: str, body: ApptStatusIn, db: DbDep, p: CurrentUser):
    a = db.get(Appointment, appointment_id)
    if a is None:
        raise HTTPException(404, "Appointment not found")
    v = db.get(Vehicle, a.vehicle_id)
    if org_scope(p) and v and v.org_id != org_scope(p):
        raise HTTPException(404, "Appointment not found")
    a.status = body.status
    db.commit()
    return _a_out(db, a)
