"""Local mirror of the cloud clearance engine.

Calls `kifaru.services.clearance_engine.decide` — the very same function the API runs — against a locally cached
snapshot of limits, vehicle registry, RFID tags, watch-list and lane calibration validity, so the lane can decide in
< 2 s with no cloud connectivity (RCS-04..10, CLD-04). Identity resolution replicates `kifaru.services.identity.resolve`
over the snapshot (the API version needs a SQLAlchemy session). The audit seed is derived from the event ULID so the
cloud can reproduce the exact decision (same inputs + same seed -> same evidence hash).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from kifaru.services import clearance_engine as ce
from kifaru.services.identity import SINGLE_SOURCE_CAP, normalise_plate
from kifaru.services.limits import DEFAULT_LIMITS, LimitSet

from .identity import AnprRead, RfidRead


@dataclass
class VehicleRecord:
    vehicle_id: str
    plate: str
    axle_config: str
    tare_kg: int
    max_gvm_kg: int
    watchlist_reason: str | None = None
    trailer_axle_config: str | None = None
    epcs: list[str] = field(default_factory=list)
    status: str = "active"


@dataclass
class Snapshot:
    version: str = "local-default"
    fetched_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    limits: dict = field(default_factory=lambda: _limits_to_dict(DEFAULT_LIMITS))
    vehicles: list[VehicleRecord] = field(default_factory=list)
    identity_min_confidence: float = 0.90
    audit_rate: float = 0.02
    calibration_valid_until: str | None = None  # ISO; None => unknown => treated as valid=False (blocks GREEN)

    def limit_set(self) -> LimitSet:
        d = dict(self.limits)
        d.pop("notes", None)
        return LimitSet(**d)

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> Snapshot:
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        d["vehicles"] = [VehicleRecord(**v) for v in d.get("vehicles", [])]
        return cls(**d)

    @classmethod
    def from_cloud_payload(cls, payload: dict) -> Snapshot:
        """Payload pushed on the `cmd` topic: {"version", "limits": {...}, "vehicles": [...], "identity_min_confidence", "audit_rate", "calibration_valid_until"}."""
        return cls(
            version=payload.get("version", "cloud"),
            limits=payload.get("limits", _limits_to_dict(DEFAULT_LIMITS)),
            vehicles=[VehicleRecord(**v) for v in payload.get("vehicles", [])],
            identity_min_confidence=payload.get("identity_min_confidence", 0.90),
            audit_rate=payload.get("audit_rate", 0.02),
            calibration_valid_until=payload.get("calibration_valid_until"),
        )

    def calibration_valid(self, at: datetime) -> bool:
        if not self.calibration_valid_until:
            return False
        return datetime.fromisoformat(self.calibration_valid_until) > at


def _limits_to_dict(ln: LimitSet) -> dict:
    d = asdict(l)
    return d


@dataclass
class IdentityResolution:
    vehicle: VehicleRecord | None
    confidence: float
    method: str
    explanation: str
    anpr_plate: str | None
    rfid_epc: str | None


def audit_seed_for(event_id: str) -> int:
    return int(hashlib.sha256(event_id.encode()).hexdigest()[:8], 16) & 0x7FFFFFFF


def measurement_input(m: dict, source: str = "live") -> ce.MeasurementInput:
    """Same construction as apps/api/kifaru/services/weighing_service.process_lane_pass."""
    return ce.MeasurementInput(
        gvm_kg=int(m["gvm_kg"]),
        gvm_u_kg=int(m["gvm_u_kg"]),
        axles=[ce.AxleInput(a["index"], int(a["load_kg"]), int(a["u_kg"]), a.get("group_no", 1)) for a in m["axles"]],
        detected_axle_config=m.get("axle_config") or "",
        quality_flags=list(m.get("quality_flags", [])),
        sensor_health={k: (v["status"] if isinstance(v, dict) else v) for k, v in m.get("sensor_health", {}).items()},
        speed_mps=float(m.get("speed_mps", 0.0)),
        source=source,
    )


class ClearanceMirror:
    def __init__(self, snapshot: Snapshot | None = None, snapshot_path: Path | None = None):
        self.snapshot_path = Path(snapshot_path) if snapshot_path else None
        if snapshot is None and self.snapshot_path and self.snapshot_path.exists():
            snapshot = Snapshot.load(self.snapshot_path)
        self.snapshot = snapshot or Snapshot()
        self._by_plate = {normalise_plate(v.plate): v for v in self.snapshot.vehicles}
        self._by_epc = {e: v for v in self.snapshot.vehicles for e in v.epcs}

    def update_snapshot(self, snapshot: Snapshot) -> None:
        self.snapshot = snapshot
        self._by_plate = {normalise_plate(v.plate): v for v in snapshot.vehicles}
        self._by_epc = {e: v for v in snapshot.vehicles for e in v.epcs}
        if self.snapshot_path:
            snapshot.save(self.snapshot_path)

    # ---------------------------------------------------------------- identity (mirror of kifaru.services.identity.resolve)
    def resolve_identity(self, anpr: AnprRead | None, rfid: RfidRead | None) -> IdentityResolution:
        plate = anpr.plate if anpr else None
        epc = rfid.epc if rfid else None
        anpr_vehicle = self._by_plate.get(normalise_plate(plate)) if plate else None
        rfid_vehicle = self._by_epc.get(epc) if epc else None
        ca = float(anpr.confidence) if (anpr and anpr_vehicle) else 0.0
        cr = float(rfid.confidence) if (rfid and rfid_vehicle) else 0.0
        if anpr_vehicle and rfid_vehicle:
            if anpr_vehicle.vehicle_id == rfid_vehicle.vehicle_id:
                return IdentityResolution(anpr_vehicle, 1.0 - (1.0 - ca) * (1.0 - cr), "rfid+anpr",
                                          f"RFID {epc} and plate {plate} both resolve to {anpr_vehicle.plate}", plate, epc)
            return IdentityResolution(None, 0.0, "conflict", f"RFID resolves to {rfid_vehicle.plate} but ANPR read {plate} ({anpr_vehicle.plate})", plate, epc)
        if rfid_vehicle:
            return IdentityResolution(rfid_vehicle, min(cr, SINGLE_SOURCE_CAP), "rfid", f"RFID {epc} -> {rfid_vehicle.plate}; ANPR unavailable/unmatched", plate, epc)
        if anpr_vehicle:
            return IdentityResolution(anpr_vehicle, min(ca, SINGLE_SOURCE_CAP), "anpr", f"ANPR {plate} -> {anpr_vehicle.plate}; RFID unavailable/unmatched", plate, epc)
        return IdentityResolution(None, 0.0, "none", "no identity evidence matched a registered vehicle", plate, epc)

    # ---------------------------------------------------------------- decision
    def decide(self, measurement: dict, anpr: AnprRead | None, rfid: RfidRead | None, event_id: str, occurred_at: datetime,
               cargo: ce.CargoInput | None = None, source: str = "live") -> tuple[ce.ClearanceResult, IdentityResolution]:
        ident = self.resolve_identity(anpr, rfid)
        v = ident.vehicle
        m_in = measurement_input(measurement, source)
        id_in = ce.IdentityInput(ident.confidence, v.vehicle_id if v else None, ident.method, ident.anpr_plate, ident.rfid_epc)
        v_in = ce.VehicleInput(v.vehicle_id, v.plate, v.axle_config, v.tare_kg, v.max_gvm_kg, v.watchlist_reason, v.trailer_axle_config) if v else None
        result = ce.decide(
            m_in, id_in, v_in, cargo,
            limits=self.snapshot.limit_set(),
            identity_min_confidence=self.snapshot.identity_min_confidence,
            audit_rate=self.snapshot.audit_rate,
            audit_seed=audit_seed_for(event_id),
            lane_calibration_valid=self.snapshot.calibration_valid(occurred_at),
        )
        return result, ident

    def decision_payload(self, result: ce.ClearanceResult, ident: IdentityResolution) -> dict:
        return {
            "decision": result.decision,
            "rules_fired": result.rules_fired,
            "margins": result.margins,
            "explanation": result.explanation,
            "evidence_hash": result.evidence_hash,
            "audit_selected": result.audit_selected,
            "audit_seed": result.audit_seed,
            "limits_version": result.limits_version,
            "engine_version": result.engine_version,
            "snapshot_version": self.snapshot.version,
            "identity": {"method": ident.method, "confidence": round(ident.confidence, 3), "vehicle_id": ident.vehicle.vehicle_id if ident.vehicle else None,
                         "explanation": ident.explanation},
        }
