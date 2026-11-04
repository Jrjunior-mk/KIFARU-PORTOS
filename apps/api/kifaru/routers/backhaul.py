"""Backhaul marketplace (Module 4): offers -> proposed matches -> two-party acceptance -> assignment -> delivery."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from kifaru_ai_agents.backhaul_matcher import BackhaulMatchingAgent

from ..deps import CurrentUser, DbDep, Principal, audit, org_scope, require_roles
from ..events import EventType, publish
from ..models import BackhaulMatch, BackhaulOffer, DeliveryRecord, Organization, Vehicle, utcnow
from ..services import ledger

router = APIRouter(prefix="/backhaul", tags=["backhaul"])
OWNER = require_roles("cargo_owner", "platform_admin")
TRANSPORTER = require_roles("transporter_admin", "dispatcher", "platform_admin")


class OfferIn(BaseModel):
    title: str = Field(min_length=3, max_length=160)
    cargo_type: str = Field(default="general", pattern="^(general|container|bulk|liquid|reefer|hazardous)$")
    mass_kg: int = Field(ge=100, le=45000)
    volume_m3: float | None = None
    length_m: float | None = None
    requires_body_types: list[str] = []
    origin: str
    origin_lat: float
    origin_lon: float
    destination: str
    dest_lat: float
    dest_lon: float
    ready_from: datetime
    deadline: datetime
    offered_price_kes: float = Field(ge=0)
    notes: str | None = None


class MatchOut(BaseModel):
    id: str
    offer_id: str
    vehicle_id: str
    plate: str
    transporter_org_id: str
    transporter_name: str | None
    score: float
    extra_km: float
    fuel_litres: float
    fuel_cost_kes: float
    revenue_kes: float
    co2_avoided_kg: float
    explanation: dict
    status: str
    transporter_decided_at: datetime | None
    owner_decided_at: datetime | None
    assigned_at: datetime | None


class OfferOut(OfferIn):
    id: str
    cargo_owner_org_id: str
    cargo_owner_name: str | None
    status: str
    created_at: datetime
    matches: list[MatchOut]


def _m_out(db, m: BackhaulMatch) -> MatchOut:
    v = db.get(Vehicle, m.vehicle_id)
    o = db.get(Organization, m.transporter_org_id)
    return MatchOut(id=m.id, offer_id=m.offer_id, vehicle_id=m.vehicle_id, plate=v.plate if v else "", transporter_org_id=m.transporter_org_id,
                    transporter_name=o.name if o else None, score=m.score, extra_km=m.extra_km, fuel_litres=m.fuel_litres, fuel_cost_kes=float(m.fuel_cost_kes),
                    revenue_kes=float(m.revenue_kes), co2_avoided_kg=m.co2_avoided_kg, explanation=m.explanation, status=m.status,
                    transporter_decided_at=m.transporter_decided_at, owner_decided_at=m.owner_decided_at, assigned_at=m.assigned_at)


def _o_out(db, o: BackhaulOffer, p) -> OfferOut:
    owner = db.get(Organization, o.cargo_owner_org_id)
    scope = org_scope(p)
    matches = [m for m in o.matches if scope is None or m.transporter_org_id == scope or o.cargo_owner_org_id == scope]
    return OfferOut(id=o.id, cargo_owner_org_id=o.cargo_owner_org_id, cargo_owner_name=owner.name if owner else None, status=o.status, created_at=o.created_at,
                    title=o.title, cargo_type=o.cargo_type, mass_kg=o.mass_kg, volume_m3=o.volume_m3, length_m=o.length_m, requires_body_types=o.requires_body_types,
                    origin=o.origin, origin_lat=o.origin_lat, origin_lon=o.origin_lon, destination=o.destination, dest_lat=o.dest_lat, dest_lon=o.dest_lon,
                    ready_from=o.ready_from, deadline=o.deadline, offered_price_kes=float(o.offered_price_kes), notes=o.notes,
                    matches=[_m_out(db, m) for m in sorted(matches, key=lambda x: -x.score)])


@router.get("/offers", response_model=list[OfferOut])
def list_offers(p: CurrentUser, db: DbDep, status: str | None = None):
    q = select(BackhaulOffer).order_by(BackhaulOffer.created_at.desc())
    if status:
        q = q.where(BackhaulOffer.status == status)
    rows = db.execute(q).scalars().all()
    scope = org_scope(p)
    if scope and p.has_role("cargo_owner") and not p.has_role("transporter_admin", "dispatcher"):
        rows = [o for o in rows if o.cargo_owner_org_id == scope]
    return [_o_out(db, o, p) for o in rows]


@router.post("/offers", response_model=OfferOut, status_code=201)
def create_offer(body: OfferIn, db: DbDep, p: Principal = Depends(OWNER)):
    if body.deadline <= body.ready_from:
        raise HTTPException(400, "deadline must be after ready_from")
    o = BackhaulOffer(cargo_owner_org_id=p.org_id, created_by=p.user.id, **body.model_dump())
    db.add(o)
    db.flush()
    ledger.append(db, "backhaul.offer_created", {"offer_id": o.id, "org": p.org_id, "mass_kg": o.mass_kg, "destination": o.destination}, producer="backhaul")
    audit(db, p, "create", "backhaul_offer", o.id)
    db.commit()
    publish(EventType.BACKHAUL_OPPORTUNITY, {"offer_id": o.id, "title": o.title, "origin": o.origin, "destination": o.destination, "mass_kg": o.mass_kg, "price_kes": float(o.offered_price_kes)})
    return _o_out(db, o, p)


@router.post("/offers/{offer_id}/match", response_model=OfferOut)
def run_matching(offer_id: str, db: DbDep, p: Principal = Depends(require_roles("cargo_owner", "transporter_admin", "dispatcher", "platform_admin"))):
    """Runs the matching agent over all available trucks and stores PROPOSED matches. Nothing is assigned."""
    o = db.get(BackhaulOffer, offer_id)
    if o is None:
        raise HTTPException(404, "Offer not found")
    if o.status not in ("open", "matched"):
        raise HTTPException(409, f"Offer is {o.status}")
    trucks = []
    for v in db.execute(select(Vehicle).where(Vehicle.status == "active")).scalars():
        if v.last_lat is None or v.last_lon is None:
            continue
        trucks.append({"vehicle_id": v.id, "payload_capacity_kg": v.payload_capacity_kg, "body_type": v.body_type, "lat": v.last_lat, "lon": v.last_lon,
                       "home_lat": -4.0435, "home_lon": 39.6682, "org_id": v.org_id})  # home = Mombasa default until fleet bases are modelled
    res = BackhaulMatchingAgent().run({"offer": {"mass_kg": o.mass_kg, "cargo_type": o.cargo_type, "origin_lat": o.origin_lat, "origin_lon": o.origin_lon,
                                                  "dest_lat": o.dest_lat, "dest_lon": o.dest_lon, "ready_from": o.ready_from, "deadline": o.deadline,
                                                  "offered_price_kes": float(o.offered_price_kes), "requires_body_types": o.requires_body_types}, "trucks": trucks})
    if not res.ok:
        raise HTTPException(500, f"matching agent failed: {res.error}")
    existing = {m.vehicle_id: m for m in o.matches}
    by_vehicle = {t["vehicle_id"]: t for t in trucks}
    for m in res.output["matches"][:10]:
        if not m["feasible"]:
            continue
        if m["vehicle_id"] in existing:
            continue
        db.add(BackhaulMatch(offer_id=o.id, vehicle_id=m["vehicle_id"], transporter_org_id=by_vehicle[m["vehicle_id"]]["org_id"], score=m["score"], extra_km=m["extra_km"],
                             fuel_litres=m["fuel_litres"], fuel_cost_kes=m["fuel_cost_kes"], revenue_kes=m["revenue_kes"], co2_avoided_kg=m["co2_avoided_kg"],
                             explanation={**m["explanation"], "agent": res.agent, "agent_version": res.version, "agent_confidence": res.confidence}))
    o.status = "matched" if res.output["feasible_count"] else o.status
    db.commit()
    db.refresh(o)
    return _o_out(db, o, p)


class DecisionIn(BaseModel):
    accept: bool
    reason: str | None = None


def _transition(db, m: BackhaulMatch, p, side: str, accept: bool) -> None:
    now = utcnow()
    if not accept:
        m.status = "rejected"
    elif side == "transporter":
        m.transporter_decided_at = now
        m.status = "assigned" if m.status == "owner_accepted" else "transporter_accepted"
    else:
        m.owner_decided_at = now
        m.status = "assigned" if m.status == "transporter_accepted" else "owner_accepted"
    if m.status == "assigned":
        m.assigned_at = now
        m.offer.status = "assigned"
        for other in m.offer.matches:
            if other.id != m.id and other.status not in ("rejected", "cancelled"):
                other.status = "cancelled"
        ledger.append(db, "backhaul.assigned", {"match_id": m.id, "offer_id": m.offer_id, "vehicle_id": m.vehicle_id}, producer="backhaul")
    audit(db, p, f"{side}_{'accept' if accept else 'reject'}", "backhaul_match", m.id, after={"status": m.status})


@router.post("/matches/{match_id}/transporter-decision", response_model=MatchOut)
def transporter_decision(match_id: str, body: DecisionIn, db: DbDep, p: Principal = Depends(TRANSPORTER)):
    m = db.get(BackhaulMatch, match_id)
    if m is None or (org_scope(p) and m.transporter_org_id != org_scope(p)):
        raise HTTPException(404, "Match not found")
    if m.status not in ("proposed", "owner_accepted"):
        raise HTTPException(409, f"Match is {m.status}")
    _transition(db, m, p, "transporter", body.accept)
    db.commit()
    return _m_out(db, m)


@router.post("/matches/{match_id}/owner-decision", response_model=MatchOut)
def owner_decision(match_id: str, body: DecisionIn, db: DbDep, p: Principal = Depends(OWNER)):
    m = db.get(BackhaulMatch, match_id)
    if m is None or (org_scope(p) and m.offer.cargo_owner_org_id != org_scope(p)):
        raise HTTPException(404, "Match not found")
    if m.status not in ("proposed", "transporter_accepted"):
        raise HTTPException(409, f"Match is {m.status}")
    _transition(db, m, p, "owner", body.accept)
    db.commit()
    return _m_out(db, m)


class DeliverIn(BaseModel):
    receiver_name: str | None = None
    notes: str | None = None


@router.post("/matches/{match_id}/deliver", response_model=MatchOut)
def deliver(match_id: str, body: DeliverIn, db: DbDep, p: Principal = Depends(TRANSPORTER)):
    m = db.get(BackhaulMatch, match_id)
    if m is None or (org_scope(p) and m.transporter_org_id != org_scope(p)):
        raise HTTPException(404, "Match not found")
    if m.status != "assigned":
        raise HTTPException(409, "Only assigned matches can be delivered")
    m.status = "delivered"
    m.offer.status = "delivered"
    db.add(DeliveryRecord(backhaul_match_id=m.id, delivered_at=utcnow(), receiver_name=body.receiver_name, notes=body.notes))
    ledger.append(db, "backhaul.delivered", {"match_id": m.id, "offer_id": m.offer_id}, producer="backhaul")
    db.commit()
    publish(EventType.SHIPMENT_DELIVERED, {"backhaul_match_id": m.id, "offer_id": m.offer_id}, org_id=m.offer.cargo_owner_org_id)
    return _m_out(db, m)


@router.get("/opportunities", response_model=list[OfferOut])
def opportunities(p: CurrentUser, db: DbDep):
    """Transporter view: open/matched offers plus matches proposed to this transporter's trucks."""
    rows = db.execute(select(BackhaulOffer).where(BackhaulOffer.status.in_(["open", "matched"])).order_by(BackhaulOffer.ready_from)).scalars().all()
    return [_o_out(db, o, p) for o in rows]
