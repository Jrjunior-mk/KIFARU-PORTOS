"""Periodic jobs worker: queue forecasts, release predictions, incident recommendations.

    python -m kifaru.workers.jobs --every 5          # minutes
    python -m kifaru.workers.jobs --once

Everything here is advisory (AI agents) or derived (forecasts); nothing overrides the deterministic clearance engine.
``run_once(db)`` is the unit of work and is what the tests call.
"""
from __future__ import annotations

import argparse
import logging
import signal
import sys
import threading
import time
from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from kifaru_ai_agents.agents_misc import OperationalIncidentAgent
from kifaru_ai_agents.release_predictor import ReleasePredictionAgent

from ..config import get_settings
from ..db import get_sessionmaker
from ..events import EventType, publish
from ..models import CargoProcessingEvent, ClearanceDecision, Incident, QueueRecord, Shipment, Warehouse, WeighingEvent, WeighingStation, utcnow
from ..services.queue_forecast import forecast_station

log = structlog.get_logger("kifaru.workers.jobs")

HISTORY_LIMIT = 96  # 24 h of 15-min observations


def _parse_iso(s: str) -> datetime:
    dt = datetime.fromisoformat(s)
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


# ------------------------------------------------------------------------------------------------- forecasts
def refresh_forecasts(db: Session) -> dict[str, list[QueueRecord]]:
    out: dict[str, list[QueueRecord]] = {}
    for st in db.execute(select(WeighingStation)).scalars().all():
        hist = db.execute(select(QueueRecord).where(QueueRecord.station_id == st.id, QueueRecord.kind == "observed").order_by(QueueRecord.ts.desc()).limit(HISTORY_LIMIT)).scalars().all()
        recs = forecast_station(st, list(reversed(hist)))
        for r in recs:
            db.add(r)
        out[st.id] = recs
    db.flush()
    return out


def _latest_observed(db: Session, station_id: str) -> QueueRecord | None:
    return db.execute(select(QueueRecord).where(QueueRecord.station_id == station_id, QueueRecord.kind == "observed").order_by(QueueRecord.ts.desc()).limit(1)).scalar_one_or_none()


def _stage_history(db: Session) -> dict[str, list[float]]:
    """Durations (hours) per stage from completed processing events of shipments — feeds the predictor when >= 20."""
    hist: dict[str, list[float]] = {}
    rows = db.execute(select(CargoProcessingEvent).order_by(CargoProcessingEvent.shipment_id, CargoProcessingEvent.occurred_at)).scalars().all()
    prev: CargoProcessingEvent | None = None
    for ev in rows:
        if prev is not None and prev.shipment_id == ev.shipment_id:
            a, b = prev.occurred_at, ev.occurred_at
            a = a if a.tzinfo else a.replace(tzinfo=UTC)
            b = b if b.tzinfo else b.replace(tzinfo=UTC)
            hist.setdefault(prev.stage, []).append(max(0.0, (b - a).total_seconds() / 3600.0))
        prev = ev
    return hist


# ------------------------------------------------------------------------------------------------- predictions
def refresh_release_predictions(db: Session) -> int:
    agent = ReleasePredictionAgent()
    now = utcnow()
    history = _stage_history(db)
    utils = [q.utilisation for q in (_latest_observed(db, st.id) for st in db.execute(select(WeighingStation)).scalars().all()) if q is not None]
    mean_util = sum(utils) / len(utils) if utils else None
    n = 0
    for sh in db.execute(select(Shipment).where(Shipment.status == "active")).scalars().all():
        last_dec = None
        if sh.vehicle_id:
            last_dec = db.execute(
                select(ClearanceDecision.decision).join(WeighingEvent, WeighingEvent.id == ClearanceDecision.weighing_event_id)
                .where(WeighingEvent.vehicle_id == sh.vehicle_id).order_by(WeighingEvent.occurred_at.desc()).limit(1)
            ).scalar_one_or_none()
        seal = sh.seals[-1].status if sh.seals else None
        wh_ready = None
        if sh.warehouse_id:
            wh = db.get(Warehouse, sh.warehouse_id)
            wh_ready = (wh.readiness_status == "ready") if wh else None
        res = agent.run({
            "stage": sh.stage, "now": now, "has_declaration": sh.declaration is not None, "seal_status": seal,
            "station_utilisation": mean_util, "warehouse_ready": wh_ready, "last_decision": last_dec, "history": history,
        })
        if not res.ok:
            log.warning("release_prediction_failed", shipment=sh.id, error=res.error)
            continue
        o = res.output
        sh.predicted_release_p10 = _parse_iso(o["p10"])
        sh.predicted_release_at = _parse_iso(o["p50"])
        sh.predicted_release_p90 = _parse_iso(o["p90"])
        sh.prediction_explanation = {
            "reasons": o.get("reasons", []), "stage_estimates_h": o.get("stage_estimates_h", {}), "remaining_stages": o.get("remaining_stages", []),
            "confidence": res.confidence, "warnings": res.warnings, "agent": f"{agent.name}@{agent.version}", "computed_at": now.isoformat(), "label": "advisory prediction",
        }
        n += 1
    db.flush()
    return n


# ------------------------------------------------------------------------------------------------- incidents
def refresh_incidents(db: Session, forecasts: dict[str, list[QueueRecord]] | None = None) -> list[Incident]:
    agent = OperationalIncidentAgent()
    created: list[Incident] = []
    for st in db.execute(select(WeighingStation)).scalars().all():
        health: dict[str, str] = {}
        for lane in st.lanes:
            for s in lane.sensors:
                health[s.serial or f"L{lane.lane_no}:{s.kind}:{s.channel}"] = s.status
        q = _latest_observed(db, st.id)
        f120 = None
        for r in (forecasts or {}).get(st.id, []):
            if r.kind == "forecast_120":
                f120 = r.queue_len
        res = agent.run({"sensor_health": health, "station_status": st.status, "queue_len": q.queue_len if q else 0, "capacity_per_hour": st.capacity_per_hour, "forecast_120_queue": f120})
        if not res.ok:
            log.warning("incident_agent_failed", station=st.code, error=res.error)
            continue
        for rec in res.output.get("incidents", []):
            if rec["severity"] not in ("high", "critical"):
                continue
            dup = db.execute(select(Incident).where(Incident.station_id == st.id, Incident.title == rec["title"], Incident.status == "open")).scalars().first()
            if dup:
                continue
            inc = Incident(station_id=st.id, severity=rec["severity"], category=rec["category"], title=rec["title"],
                           details={"action": rec.get("action"), "agent": f"{agent.name}@{agent.version}", "confidence": res.confidence, "inputs": {"queue_len": q.queue_len if q else 0, "forecast_120_queue": f120}},
                           status="open", opened_at=utcnow(), raised_by="operational_incident_agent")
            db.add(inc)
            db.flush()
            publish(EventType.INCIDENT_OPENED, {"incident_id": inc.id, "severity": inc.severity, "category": inc.category, "title": inc.title, "station_code": st.code}, station_id=st.id, source="jobs-worker")
            created.append(inc)
    return created


# ------------------------------------------------------------------------------------------------- orchestration
def run_once(db: Session) -> dict:
    t0 = time.perf_counter()
    forecasts = refresh_forecasts(db)
    n_pred = refresh_release_predictions(db)
    incidents = refresh_incidents(db, forecasts)
    db.commit()
    summary = {"stations_forecast": len(forecasts), "forecast_records": sum(len(v) for v in forecasts.values()), "shipments_predicted": n_pred,
               "incidents_opened": len(incidents), "duration_ms": int((time.perf_counter() - t0) * 1000), "at": datetime.now(UTC).isoformat()}
    log.info("jobs_run", **summary)
    return summary


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="KIFARU PORTOS periodic jobs worker")
    p.add_argument("--every", type=float, default=5.0, help="minutes between runs")
    p.add_argument("--once", action="store_true")
    a = p.parse_args(argv)
    logging.basicConfig(level=get_settings().log_level, stream=sys.stdout)
    Session = get_sessionmaker()
    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    while True:
        with Session() as db:
            try:
                print(run_once(db))
            except Exception as exc:  # noqa: BLE001 - a failing cycle must not kill the worker
                db.rollback()
                log.exception("jobs_cycle_failed", error=str(exc))
        if a.once or stop.wait(a.every * 60.0):
            return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
