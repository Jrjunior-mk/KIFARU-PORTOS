"""Environmental intelligence (Module 8). Every number is a MODELLED estimate with the formulas exposed."""
from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from kifaru_ai_agents.environmental import FACTORS, EnvironmentalAgent

from ..deps import CurrentUser, DbDep
from ..models import BackhaulMatch, ClearanceDecision, QueueRecord, WeighingEvent, utcnow

router = APIRouter(prefix="/environment", tags=["environment"])


class EnvReportOut(BaseModel):
    period_hours: int
    station_id: str | None
    inputs: dict
    baseline: dict
    platform: dict
    savings: dict
    factors: dict
    label: str
    assumptions: list[str]
    agent_confidence: float


@router.get("/report", response_model=EnvReportOut)
def report(p: CurrentUser, db: DbDep, hours: int = 24, station_id: str | None = None):
    since = utcnow() - timedelta(hours=hours)
    q = select(ClearanceDecision.decision, func.count()).join(WeighingEvent, WeighingEvent.id == ClearanceDecision.weighing_event_id).where(ClearanceDecision.decided_at >= since)
    if station_id:
        q = q.where(WeighingEvent.station_id == station_id)
    by = {"GREEN": 0, "AMBER": 0, "RED": 0}
    for d, c in db.execute(q.group_by(ClearanceDecision.decision)).all():
        by[d] = c
    wq = select(func.avg(QueueRecord.avg_wait_s)).where(QueueRecord.kind == "observed", QueueRecord.ts >= since)
    if station_id:
        wq = wq.where(QueueRecord.station_id == station_id)
    avg_wait = float(db.execute(wq).scalar() or 900.0)
    assigned = db.execute(select(BackhaulMatch).where(BackhaulMatch.status.in_(["assigned", "delivered"]), BackhaulMatch.created_at >= since)).scalars().all()
    empty_avoided = sum(float(m.explanation.get("km_loaded", 0.0)) for m in assigned)
    inputs = {"stops_avoided": by["GREEN"], "stops_made": by["AMBER"] + by["RED"], "avg_queue_wait_s": avg_wait, "empty_km": empty_avoided, "empty_km_avoided": empty_avoided, "detour_km": 0.0}
    res = EnvironmentalAgent().run(inputs)
    o = res.output
    return EnvReportOut(period_hours=hours, station_id=station_id, inputs=inputs, baseline=o["baseline"], platform=o["platform"], savings=o["savings"], factors=o["factors"],
                        label=o["label"], assumptions=o["assumptions"], agent_confidence=res.confidence)


class WhatIfIn(BaseModel):
    stops_avoided: int = Field(ge=0)
    stops_made: int = Field(ge=0)
    avg_queue_wait_s: int = Field(ge=0, le=86400)
    empty_km: float = Field(ge=0, default=0)
    empty_km_avoided: float = Field(ge=0, default=0)
    detour_km: float = Field(ge=0, default=0)
    factors: dict | None = None


@router.post("/what-if", response_model=dict)
def what_if(body: WhatIfIn, p: CurrentUser):
    res = EnvironmentalAgent().run(body.model_dump())
    return {"ok": res.ok, **res.output, "agent_confidence": res.confidence, "explanation": res.explanation}


@router.get("/factors")
def factors():
    return {"factors": FACTORS, "formulas": {
        "idling_fuel_l": "idle_hours * idle_l_per_h",
        "stop_penalty_l": "stops * stop_penalty_l",
        "empty_trip_fuel_l": "empty_km * fuel_l_per_km_empty",
        "detour_fuel_l": "detour_km * fuel_l_per_km_loaded",
        "co2_kg": "litres * co2_kg_per_l",
        "cost_kes": "litres * diesel_kes_per_l",
        "savings": "baseline(all trucks stop, all empty km driven) - platform(only AMBER/RED stop, matched empty km removed)",
    }, "label": "modelled estimates; not measured environmental achievements"}
