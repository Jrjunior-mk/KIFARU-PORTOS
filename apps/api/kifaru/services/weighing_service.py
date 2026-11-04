"""Orchestrates one lane pass: persist measurement -> resolve identity -> deterministic decision -> ticket -> ledger -> events.

Used by both the edge ingest endpoint (`source=live`, measurement computed on the gateway) and the simulator
(`source=simulated`). The source is never dropped.
"""
from __future__ import annotations

import time
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..events import EventType, publish
from ..models import (
    AxleMeasurement,
    ClearanceDecision,
    ElectronicSeal,
    IdentityEvent,
    Lane,
    Shipment,
    Vehicle,
    WeighingEvent,
    utcnow,
)
from ..security import sign_payload
from . import clearance_engine as ce
from . import identity as identity_svc
from . import ledger, tickets
from .limits import DEFAULT_LIMITS

INSTRUCTIONS = {
    "GREEN": "Continue — no stop required",
    "AMBER": "Proceed to the static scale for verification",
    "RED": "Stop for inspection",
}


def _lane_calibration_valid(lane: Lane, at: datetime) -> bool:
    if lane.calibration_valid_to is None:
        return False
    v = lane.calibration_valid_to
    if v.tzinfo is None:
        v = v.replace(tzinfo=UTC)
    return v >= at


def process_lane_pass(
    db: Session,
    lane: Lane,
    measurement: dict,
    anpr_plate: str | None,
    anpr_conf: float | None,
    rfid_epc: str | None,
    rfid_conf: float | None,
    occurred_at: datetime | None = None,
    source: str = "simulated",
    edge_event_id: str | None = None,
    raw_ref: str | None = None,
    ambient_temp_c: float | None = None,
) -> WeighingEvent:
    """`measurement` is the dict form of `kifaru_wim_dsp.WimMeasurement.to_dict()`."""
    t_start = time.perf_counter()
    s = get_settings()
    occurred_at = occurred_at or utcnow()

    if edge_event_id:
        existing = db.execute(select(WeighingEvent).where(WeighingEvent.edge_event_id == edge_event_id)).scalar_one_or_none()
        if existing:
            return existing  # idempotent replay from store-and-forward

    publish(EventType.TRUCK_DETECTED, {"lane_id": lane.id}, station_id=lane.station_id, source=source)
    publish(EventType.WEIGHING_STARTED, {"lane_id": lane.id}, station_id=lane.station_id, source=source)

    ident = identity_svc.resolve(db, anpr_plate, anpr_conf, rfid_epc, rfid_conf)
    vehicle: Vehicle | None = ident.vehicle

    # cargo context: the active shipment assigned to this vehicle, if any
    shipment: Shipment | None = None
    if vehicle:
        shipment = db.execute(
            select(Shipment).where(Shipment.vehicle_id == vehicle.id, Shipment.status == "active").order_by(Shipment.created_at.desc())
        ).scalars().first()
    seal_status = None
    if shipment:
        seal = db.execute(select(ElectronicSeal).where(ElectronicSeal.shipment_id == shipment.id).order_by(ElectronicSeal.created_at.desc())).scalars().first()
        seal_status = seal.status if seal else None

    ev = WeighingEvent(
        lane_id=lane.id,
        station_id=lane.station_id,
        vehicle_id=vehicle.id if vehicle else None,
        shipment_id=shipment.id if shipment else None,
        occurred_at=occurred_at,
        speed_mps=float(measurement.get("speed_mps", 0.0)),
        gvm_kg=int(measurement["gvm_kg"]),
        gvm_uncertainty_kg=int(measurement["gvm_u_kg"]),
        axle_count=len(measurement["axles"]),
        detected_axle_config=measurement.get("axle_config"),
        class_code=measurement.get("class_code"),
        quality_flags=list(measurement.get("quality_flags", [])),
        sensor_health={k: v["status"] if isinstance(v, dict) else v for k, v in measurement.get("sensor_health", {}).items()},
        pavement_temp_c=measurement.get("pavement_temp_c"),
        ambient_temp_c=ambient_temp_c,
        raw_ref=raw_ref,
        source=source,
        kind="wim",
        edge_event_id=edge_event_id,
    )
    db.add(ev)
    db.flush()
    for a in measurement["axles"]:
        db.add(
            AxleMeasurement(
                weighing_event_id=ev.id,
                axle_index=a["index"],
                load_kg=int(a["load_kg"]),
                uncertainty_kg=int(a["u_kg"]),
                spacing_to_next_m=a.get("spacing_to_next_m"),
                group_no=a.get("group_no", 1),
            )
        )
    db.add(
        IdentityEvent(
            weighing_event_id=ev.id,
            anpr_plate=anpr_plate,
            anpr_confidence=anpr_conf,
            rfid_epc=rfid_epc,
            rfid_confidence=rfid_conf,
            fused_vehicle_id=vehicle.id if vehicle else None,
            confidence=ident.confidence,
            method=ident.method,
            explanation=ident.explanation,
        )
    )
    publish(
        EventType.TRUCK_IDENTIFIED,
        {"weighing_event_id": ev.id, "plate": vehicle.plate if vehicle else anpr_plate, "confidence": ident.confidence, "method": ident.method},
        station_id=lane.station_id,
        org_id=vehicle.org_id if vehicle else "platform",
        source=source,
    )

    # ------------------------------------------------------------ decision
    m_in = ce.MeasurementInput(
        gvm_kg=ev.gvm_kg,
        gvm_u_kg=ev.gvm_uncertainty_kg,
        axles=[ce.AxleInput(a["index"], a["load_kg"], a["u_kg"], a.get("group_no", 1)) for a in measurement["axles"]],
        detected_axle_config=ev.detected_axle_config or "",
        quality_flags=ev.quality_flags,
        sensor_health=ev.sensor_health,
        speed_mps=ev.speed_mps,
        source=source,
    )
    id_in = ce.IdentityInput(ident.confidence, vehicle.id if vehicle else None, ident.method, anpr_plate, rfid_epc)
    v_in = (
        ce.VehicleInput(vehicle.id, vehicle.plate, vehicle.axle_config, vehicle.tare_kg, vehicle.max_gvm_kg, vehicle.watchlist_reason)
        if vehicle
        else None
    )
    c_in = ce.CargoInput(
        shipment_ref=shipment.reference if shipment else None,
        declared_mass_kg=shipment.declared_mass_kg if shipment else None,
        vgm_kg=shipment.vgm_kg if shipment else None,
        seal_status=seal_status,
    )
    result = ce.decide(
        m_in,
        id_in,
        v_in,
        c_in,
        limits=DEFAULT_LIMITS,
        identity_min_confidence=s.identity_min_confidence,
        audit_rate=s.audit_sample_rate,
        lane_calibration_valid=_lane_calibration_valid(lane, occurred_at),
    )
    latency_ms = int((time.perf_counter() - t_start) * 1000)
    dec = ClearanceDecision(
        weighing_event_id=ev.id,
        decision=result.decision,
        rules_fired=result.rules_fired,
        margins=result.margins,
        limits_version=result.limits_version,
        engine_version=result.engine_version,
        audit_selected=result.audit_selected,
        evidence_hash=result.evidence_hash,
        signature=sign_payload({"evidence_hash": result.evidence_hash, "decision": result.decision}),
        decided_at=utcnow(),
        latency_ms=latency_ms,
        explanation=result.explanation,
    )
    db.add(dec)
    db.flush()

    station_code = lane.station.code if lane.station else "UNKNOWN"
    ticket = tickets.issue(db, ev, dec, "prescreen", vehicle.plate if vehicle else anpr_plate, station_code)

    ledger.append(
        db,
        "weighing.completed",
        {"weighing_event_id": ev.id, "gvm_kg": ev.gvm_kg, "u_kg": ev.gvm_uncertainty_kg, "axles": ev.axle_count, "source": source},
        station_id=lane.station_id,
        producer=f"lane:{lane.id}",
        occurred_at=occurred_at,
    )
    ledger.append(
        db,
        "clearance.decided",
        {"decision_id": dec.id, "weighing_event_id": ev.id, "decision": dec.decision, "evidence_hash": dec.evidence_hash, "ticket_id": ticket.id},
        station_id=lane.station_id,
        producer="clearance-engine",
    )

    # Tenant scoping: vehicle-level events are tagged with the owning organisation so WebSocket clients of other
    # transporters never receive them. Unregistered vehicles are tagged "platform" (visible to platform-wide roles only).
    org_id = vehicle.org_id if vehicle else "platform"
    payload = {
        "weighing_event_id": ev.id,
        "decision_id": dec.id,
        "decision": dec.decision,
        "instruction": INSTRUCTIONS[dec.decision],
        "plate": vehicle.plate if vehicle else anpr_plate,
        "vehicle_id": vehicle.id if vehicle else None,
        "shipment_id": shipment.id if shipment else None,
        "gvm_kg": ev.gvm_kg,
        "u_kg": ev.gvm_uncertainty_kg,
        "axle_config": ev.detected_axle_config,
        "lane_id": lane.id,
        "ticket_id": ticket.id,
        "ticket_qr_token": ticket.qr_token,
        "latency_ms": latency_ms,
        "source": source,
        "rules_fired": [r["rule"] for r in dec.rules_fired],
    }
    publish(EventType.WEIGHING_COMPLETED, payload, station_id=lane.station_id, org_id=org_id, source=source)
    publish(EventType.CLEARANCE_DECIDED, payload, station_id=lane.station_id, org_id=org_id, source=source)
    if dec.decision in ("AMBER", "RED"):
        publish(EventType.TRUCK_DIVERTED, payload, station_id=lane.station_id, org_id=org_id, source=source)
    else:
        publish(EventType.TRUCK_RELEASED, payload, station_id=lane.station_id, org_id=org_id, source=source)
    if shipment:
        shipment.stage = "weighing_verification" if dec.decision != "GREEN" else shipment.stage
    return ev
