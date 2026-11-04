"""Vehicle identity fusion: combine an ANPR read and an RFID read into one identity with a confidence.

Rules (deterministic, explainable):
  * RFID EPC resolves to a vehicle via the tag registry; ANPR plate resolves via the vehicle registry.
  * Both agree            -> method rfid+anpr, confidence = 1 - (1-c_rfid)(1-c_anpr) (independent evidence).
  * Only one available    -> that method's confidence, capped at 0.95 (single-source cap).
  * Both present, disagree-> method conflict, confidence 0 (clearance engine treats this as RED: possible cloning).
  * Neither               -> none, confidence 0.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import RfidTag, Vehicle

SINGLE_SOURCE_CAP = 0.95


@dataclass
class IdentityResolution:
    vehicle: Vehicle | None
    confidence: float
    method: str
    explanation: str
    anpr_vehicle_id: str | None = None
    rfid_vehicle_id: str | None = None


def normalise_plate(plate: str | None) -> str | None:
    if not plate:
        return None
    return "".join(ch for ch in plate.upper() if ch.isalnum())


def resolve(db: Session, anpr_plate: str | None, anpr_conf: float | None, rfid_epc: str | None, rfid_conf: float | None) -> IdentityResolution:
    anpr_vehicle = None
    if anpr_plate:
        norm = normalise_plate(anpr_plate)
        anpr_vehicle = db.execute(select(Vehicle).where(Vehicle.plate_norm == norm)).scalars().first()
    rfid_vehicle = None
    if rfid_epc:
        tag = db.execute(select(RfidTag).where(RfidTag.epc == rfid_epc, RfidTag.revoked_at.is_(None))).scalar_one_or_none()
        if tag:
            rfid_vehicle = tag.vehicle

    ca = float(anpr_conf or 0.0) if anpr_vehicle else 0.0
    cr = float(rfid_conf or 0.0) if rfid_vehicle else 0.0

    if anpr_vehicle and rfid_vehicle:
        if anpr_vehicle.id == rfid_vehicle.id:
            conf = 1.0 - (1.0 - ca) * (1.0 - cr)
            return IdentityResolution(anpr_vehicle, conf, "rfid+anpr", f"RFID {rfid_epc} and plate {anpr_plate} both resolve to {anpr_vehicle.plate}", anpr_vehicle.id, rfid_vehicle.id)
        return IdentityResolution(None, 0.0, "conflict", f"RFID resolves to {rfid_vehicle.plate} but ANPR read {anpr_plate} ({anpr_vehicle.plate})", anpr_vehicle.id, rfid_vehicle.id)
    if rfid_vehicle:
        return IdentityResolution(rfid_vehicle, min(cr, SINGLE_SOURCE_CAP), "rfid", f"RFID {rfid_epc} -> {rfid_vehicle.plate}; ANPR unavailable/unmatched", None, rfid_vehicle.id)
    if anpr_vehicle:
        return IdentityResolution(anpr_vehicle, min(ca, SINGLE_SOURCE_CAP), "anpr", f"ANPR {anpr_plate} -> {anpr_vehicle.plate}; RFID unavailable/unmatched", anpr_vehicle.id, None)
    return IdentityResolution(None, 0.0, "none", "no identity evidence matched a registered vehicle")
