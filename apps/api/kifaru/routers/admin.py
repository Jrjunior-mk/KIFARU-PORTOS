"""Administration: users, roles, audit log, ledger verification, incidents, system health, agent catalogue."""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from ..schemas.common import Email
from sqlalchemy import func, select, text

from kifaru_ai_agents.orchestrator import Orchestrator

from ..config import get_settings
from ..deps import CurrentUser, DbDep, audit, require_roles, Principal
from ..events import bus
from ..models import ROLE_NAMES, AuditEvent, Incident, LedgerEvent, Organization, Role, User, UserPII, WeighingEvent, WeighingStation, utcnow
from ..security import hash_password, public_key_b64
from ..services import ledger

router = APIRouter(prefix="/admin", tags=["admin"])
ADMIN = require_roles("platform_admin")
AUDITOR = require_roles("platform_admin", "auditor", "regulator_readonly")


class UserOut(BaseModel):
    id: str
    email: str
    full_name: str
    org_id: str | None
    org_name: str | None
    roles: list[str]
    is_active: bool
    mfa_enabled: bool
    last_login_at: datetime | None


def _u_out(db, u: User) -> UserOut:
    org = db.get(Organization, u.org_id) if u.org_id else None
    return UserOut(id=u.id, email=u.email, full_name=u.pii.full_name if u.pii else "", org_id=u.org_id, org_name=org.name if org else None,
                   roles=u.role_names, is_active=u.is_active, mfa_enabled=u.mfa_enabled, last_login_at=u.last_login_at)


@router.get("/users", response_model=list[UserOut])
def list_users(db: DbDep, p: Principal = Depends(ADMIN)):
    return [_u_out(db, u) for u in db.execute(select(User).order_by(User.email)).scalars()]


class UserIn(BaseModel):
    email: Email
    password: str = Field(min_length=10)
    full_name: str
    org_id: str | None = None
    roles: list[str]
    phone: str | None = None


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(body: UserIn, db: DbDep, p: Principal = Depends(ADMIN)):
    if db.execute(select(User).where(User.email == body.email.lower())).scalar_one_or_none():
        raise HTTPException(409, "Email exists")
    bad = [r for r in body.roles if r not in ROLE_NAMES]
    if bad:
        raise HTTPException(400, f"Unknown roles {bad}")
    u = User(email=body.email.lower(), password_hash=hash_password(body.password), org_id=body.org_id)
    u.roles = list(db.execute(select(Role).where(Role.name.in_(body.roles))).scalars())
    db.add(u)
    db.flush()
    db.add(UserPII(user_id=u.id, full_name=body.full_name, phone_enc=body.phone))
    audit(db, p, "create", "user", u.id, after={"email": u.email, "roles": body.roles})
    db.commit()
    return _u_out(db, u)


class UserPatch(BaseModel):
    roles: list[str] | None = None
    is_active: bool | None = None
    org_id: str | None = None


@router.patch("/users/{user_id}", response_model=UserOut)
def patch_user(user_id: str, body: UserPatch, db: DbDep, p: Principal = Depends(ADMIN)):
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(404, "User not found")
    before = {"roles": u.role_names, "is_active": u.is_active, "org_id": u.org_id}
    if body.roles is not None:
        u.roles = list(db.execute(select(Role).where(Role.name.in_(body.roles))).scalars())
    if body.is_active is not None:
        u.is_active = body.is_active
    if body.org_id is not None:
        u.org_id = body.org_id
    audit(db, p, "update", "user", u.id, before=before, after=body.model_dump(exclude_none=True))
    db.commit()
    return _u_out(db, u)


@router.get("/roles")
def roles(p: Principal = Depends(ADMIN)):
    return ROLE_NAMES


class AuditOut(BaseModel):
    id: str
    actor_user_id: str | None
    action: str
    entity: str
    entity_id: str | None
    before: dict | None
    after: dict | None
    at: datetime


@router.get("/audit", response_model=list[AuditOut])
def audit_log(db: DbDep, p: Principal = Depends(AUDITOR), entity: str | None = None, limit: int = Query(100, le=1000)):
    q = select(AuditEvent).order_by(AuditEvent.at.desc()).limit(limit)
    if entity:
        q = q.where(AuditEvent.entity == entity)
    return [AuditOut(id=a.id, actor_user_id=a.actor_user_id, action=a.action, entity=a.entity, entity_id=a.entity_id, before=a.before, after=a.after, at=a.at) for a in db.execute(q).scalars()]


class LedgerOut(BaseModel):
    event_id: str
    seq: int
    type: str
    payload: dict
    station_id: str | None
    producer: str
    prev_hash: str
    hash: str
    signature: str
    occurred_at: datetime


@router.get("/ledger", response_model=list[LedgerOut])
def ledger_tail(db: DbDep, p: Principal = Depends(AUDITOR), limit: int = Query(100, le=1000), type: str | None = None):
    q = select(LedgerEvent).order_by(LedgerEvent.seq.desc()).limit(limit)
    if type:
        q = q.where(LedgerEvent.type == type)
    return [LedgerOut(event_id=e.event_id, seq=e.seq, type=e.type, payload=e.payload, station_id=e.station_id, producer=e.producer, prev_hash=e.prev_hash, hash=e.hash, signature=e.signature, occurred_at=e.occurred_at) for e in db.execute(q).scalars()]


@router.get("/ledger/verify")
def ledger_verify(db: DbDep, p: Principal = Depends(AUDITOR)):
    return {**ledger.verify_chain(db), "public_key": public_key_b64(), "signer_key_id": get_settings().signing_key_id}


class IncidentOut(BaseModel):
    id: str
    station_id: str | None
    severity: str
    category: str
    title: str
    details: dict
    status: str
    opened_at: datetime
    closed_at: datetime | None
    raised_by: str


@router.get("/incidents", response_model=list[IncidentOut])
def incidents(db: DbDep, p: CurrentUser, status: str | None = "open"):
    q = select(Incident).order_by(Incident.opened_at.desc()).limit(200)
    if status:
        q = q.where(Incident.status == status)
    return [IncidentOut(id=i.id, station_id=i.station_id, severity=i.severity, category=i.category, title=i.title, details=i.details, status=i.status, opened_at=i.opened_at, closed_at=i.closed_at, raised_by=i.raised_by) for i in db.execute(q).scalars()]


class IncidentIn(BaseModel):
    station_id: str | None = None
    severity: str = Field(default="medium", pattern="^(low|medium|high|critical)$")
    category: str = Field(pattern="^(station_failure|sensor_fault|security|traffic|cargo_anomaly|other)$")
    title: str
    details: dict = {}


@router.post("/incidents", response_model=IncidentOut, status_code=201)
def open_incident(body: IncidentIn, db: DbDep, p: Principal = Depends(require_roles("platform_admin", "port_controller", "weighbridge_operator"))):
    i = Incident(opened_at=utcnow(), raised_by=p.user.email, **body.model_dump())
    db.add(i)
    db.flush()
    from ..events import EventType, publish

    publish(EventType.INCIDENT_OPENED, {"incident_id": i.id, "title": i.title, "severity": i.severity, "station_id": i.station_id}, station_id=i.station_id)
    db.commit()
    return IncidentOut(id=i.id, station_id=i.station_id, severity=i.severity, category=i.category, title=i.title, details=i.details, status=i.status, opened_at=i.opened_at, closed_at=i.closed_at, raised_by=i.raised_by)


@router.post("/incidents/{incident_id}/close", response_model=IncidentOut)
def close_incident(incident_id: str, db: DbDep, p: Principal = Depends(require_roles("platform_admin", "port_controller", "weighbridge_operator"))):
    i = db.get(Incident, incident_id)
    if i is None:
        raise HTTPException(404, "Not found")
    i.status, i.closed_at = "closed", utcnow()
    st = db.get(WeighingStation, i.station_id) if i.station_id else None
    if st and i.category == "station_failure" and not db.execute(select(Incident).where(Incident.station_id == st.id, Incident.status == "open", Incident.id != i.id)).scalars().first():
        st.status = "operational"
    audit(db, p, "close", "incident", i.id)
    db.commit()
    return IncidentOut(id=i.id, station_id=i.station_id, severity=i.severity, category=i.category, title=i.title, details=i.details, status=i.status, opened_at=i.opened_at, closed_at=i.closed_at, raised_by=i.raised_by)


@router.get("/system/health")
def system_health(db: DbDep, p: Principal = Depends(require_roles("platform_admin", "port_controller", "auditor"))):
    s = get_settings()
    db_ok = db.execute(text("SELECT 1")).scalar() == 1
    since = utcnow() - timedelta(hours=1)
    return {
        "env": s.env, "version": s.api_version, "database": "ok" if db_ok else "down", "database_kind": "sqlite" if s.is_sqlite else "postgresql",
        "redis": "configured" if s.redis_url else "not configured (single instance)", "mqtt": "configured" if s.mqtt_host else "not configured",
        "weighings_last_hour": db.execute(select(func.count()).select_from(WeighingEvent).where(WeighingEvent.occurred_at >= since)).scalar_one(),
        "ws_subscribers": len(bus._subs), "events_recent": len(bus.recent(200)), "signing_key_id": s.signing_key_id,
    }


@router.get("/agents")
def agents_catalogue(p: CurrentUser):
    return Orchestrator().catalogue()
