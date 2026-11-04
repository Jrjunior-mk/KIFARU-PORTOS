"""Deterministic, evidence-based rolling clearance engine (Module 2).

Decision outputs: GREEN (continue), AMBER (static verification), RED (inspection).

Design rules (non-negotiable, see RTM RCS-04..RCS-10, AGT-02):
  * The engine is a pure function of its inputs; no randomness except the audit sampler, which is seeded and logged.
  * AI outputs (identity confidence, anomaly score) are *inputs*; thresholds are configuration, not learned.
  * Any measurement-quality deficiency blocks GREEN. Nothing here can issue a legal certificate: the static scale does.
  * Every decision returns the full list of rules evaluated, the margins used, and an evidence hash.

Severity resolution: if any RED rule fires -> RED; else if any AMBER rule fires -> AMBER; else GREEN.
"""
from __future__ import annotations

import hashlib
import json
import random
from dataclasses import asdict, dataclass, field
from typing import Literal

from .limits import DEFAULT_LIMITS, LimitSet, parse_axle_config

ENGINE_VERSION = "clr-1.2.0"
Decision = Literal["GREEN", "AMBER", "RED"]

# quality flags that make a measurement unusable for an automatic GREEN
BLOCKING_QUALITY_FLAGS = {
    "sensor_fault",
    "no_axles_detected",
    "speed_unavailable",
    "speed_out_of_range",
    "insufficient_rows",
    "axle_load_missing",
    "calibration_expired",
    "calibration_missing",
}
DEGRADING_QUALITY_FLAGS = {"sensor_degraded", "high_uncertainty", "lane_degraded"}


@dataclass
class AxleInput:
    index: int
    load_kg: float
    u_kg: float  # expanded uncertainty (k=2)
    group_no: int


@dataclass
class MeasurementInput:
    gvm_kg: float
    gvm_u_kg: float
    axles: list[AxleInput]
    detected_axle_config: str
    quality_flags: list[str] = field(default_factory=list)
    sensor_health: dict[str, str] = field(default_factory=dict)  # name -> ok|degraded|fault
    speed_mps: float | None = None
    source: str = "simulated"


@dataclass
class IdentityInput:
    confidence: float
    vehicle_id: str | None
    method: str = "none"  # rfid+anpr | rfid | anpr | none | conflict
    anpr_plate: str | None = None
    rfid_epc: str | None = None


@dataclass
class VehicleInput:
    vehicle_id: str
    plate: str
    axle_config: str
    tare_kg: int
    max_gvm_kg: int
    watchlist_reason: str | None = None
    trailer_axle_config: str | None = None


@dataclass
class CargoInput:
    shipment_ref: str | None = None
    declared_mass_kg: int | None = None
    vgm_kg: int | None = None
    seal_status: str | None = None  # armed | breached | removed | unknown | None
    declaration_status: str | None = None
    anomaly_score: float | None = None  # advisory AI input in [0,1]


@dataclass
class RuleResult:
    rule: str
    severity: Literal["RED", "AMBER", "INFO"]
    fired: bool
    detail: str


@dataclass
class ClearanceResult:
    decision: Decision
    rules: list[RuleResult]
    margins: dict
    explanation: str
    evidence_hash: str
    audit_selected: bool
    audit_seed: int | None
    limits_version: str
    engine_version: str = ENGINE_VERSION

    @property
    def rules_fired(self) -> list[dict]:
        return [asdict(r) for r in self.rules if r.fired]

    def to_dict(self) -> dict:
        return {
            "decision": self.decision,
            "rules": [asdict(r) for r in self.rules],
            "rules_fired": self.rules_fired,
            "margins": self.margins,
            "explanation": self.explanation,
            "evidence_hash": self.evidence_hash,
            "audit_selected": self.audit_selected,
            "audit_seed": self.audit_seed,
            "limits_version": self.limits_version,
            "engine_version": self.engine_version,
        }


def _group_loads(axles: list[AxleInput]) -> list[tuple[int, float, float]]:
    """Returns [(group_no, load_kg, u_kg)] with uncertainties combined in quadrature."""
    groups: dict[int, list[AxleInput]] = {}
    for a in axles:
        groups.setdefault(a.group_no, []).append(a)
    out = []
    for g in sorted(groups):
        load = sum(a.load_kg for a in groups[g])
        u = (sum((a.u_kg) ** 2 for a in groups[g])) ** 0.5
        out.append((g, load, u))
    return out


def decide(
    m: MeasurementInput,
    identity: IdentityInput,
    vehicle: VehicleInput | None,
    cargo: CargoInput | None = None,
    limits: LimitSet = DEFAULT_LIMITS,
    identity_min_confidence: float = 0.90,
    audit_rate: float = 0.02,
    audit_seed: int | None = None,
    lane_calibration_valid: bool = True,
) -> ClearanceResult:
    rules: list[RuleResult] = []
    cargo = cargo or CargoInput()
    flags = set(m.quality_flags)
    if not lane_calibration_valid:
        flags.add("calibration_expired")

    # ---------------------------------------------------------------- limits for this vehicle
    group_sizes = [len([a for a in m.axles if a.group_no == g]) for g in sorted({a.group_no for a in m.axles})]
    gvm_limit = limits.gvm_limit_for_config(group_sizes) if group_sizes else limits.gvm_max_kg
    if vehicle is not None:
        gvm_limit = min(gvm_limit, vehicle.max_gvm_kg) if vehicle.max_gvm_kg else gvm_limit
    gvm_tol = gvm_limit * (1 + limits.gvm_tolerance_pct / 100.0)

    margins: dict = {
        "gvm": {
            "measured_kg": round(m.gvm_kg),
            "u_kg": round(m.gvm_u_kg),
            "limit_kg": gvm_limit,
            "limit_with_tolerance_kg": round(gvm_tol),
            "margin_kg": round(gvm_tol - (m.gvm_kg + m.gvm_u_kg + limits.green_safety_margin_kg)),
        },
        "groups": [],
        "identity": {"confidence": round(identity.confidence, 3), "threshold": identity_min_confidence, "method": identity.method},
        "quality_flags": sorted(flags),
    }

    # ---------------------------------------------------------------- quality rules (block GREEN)
    blocking = sorted(flags & BLOCKING_QUALITY_FLAGS)
    rules.append(
        RuleResult(
            "QUALITY_BLOCKING",
            "AMBER",
            bool(blocking),
            f"measurement quality insufficient for automatic clearance: {blocking}" if blocking else "measurement quality acceptable",
        )
    )
    degrading = sorted(flags & DEGRADING_QUALITY_FLAGS)
    rules.append(
        RuleResult("QUALITY_DEGRADED", "AMBER", bool(degrading), f"degraded measurement: {degrading}" if degrading else "no degradation flags")
    )
    faults = sorted(k for k, v in m.sensor_health.items() if v == "fault")
    rules.append(RuleResult("SENSOR_FAULT", "AMBER", bool(faults), f"sensor fault on {faults}" if faults else "all sensors healthy or degraded only"))

    # ---------------------------------------------------------------- weight rules
    certain_over = (m.gvm_kg - m.gvm_u_kg) > gvm_tol
    possible_over = (m.gvm_kg + m.gvm_u_kg + limits.green_safety_margin_kg) > gvm_tol
    rules.append(
        RuleResult(
            "GVM_OVER_CERTAIN",
            "RED",
            certain_over,
            f"GVM {m.gvm_kg:.0f} kg minus U {m.gvm_u_kg:.0f} kg exceeds {gvm_tol:.0f} kg" if certain_over else "GVM not certainly over limit",
        )
    )
    rules.append(
        RuleResult(
            "GVM_OVER_POSSIBLE",
            "AMBER",
            possible_over and not certain_over,
            f"GVM {m.gvm_kg:.0f} kg plus U {m.gvm_u_kg:.0f} kg plus margin exceeds {gvm_tol:.0f} kg; static verification required"
            if (possible_over and not certain_over)
            else "GVM clear of limit with margin",
        )
    )

    any_group_certain = False
    any_group_possible = False
    for idx, (g, load, u) in enumerate(_group_loads(m.axles)):
        size = len([a for a in m.axles if a.group_no == g])
        lim = limits.group_limit_kg(idx, size)
        lim_tol = lim * (1 + limits.axle_tolerance_pct / 100.0)
        certain = (load - u) > lim_tol
        possible = (load + u + limits.green_safety_margin_kg) > lim_tol
        any_group_certain |= certain
        any_group_possible |= possible and not certain
        margins["groups"].append(
            {
                "group_no": g,
                "axles": size,
                "measured_kg": round(load),
                "u_kg": round(u),
                "limit_kg": lim,
                "limit_with_tolerance_kg": round(lim_tol),
                "status": "over" if certain else ("marginal" if possible else "ok"),
            }
        )
    rules.append(RuleResult("AXLE_GROUP_OVER_CERTAIN", "RED", any_group_certain, "an axle group exceeds its limit beyond uncertainty" if any_group_certain else "no axle group certainly over"))
    rules.append(RuleResult("AXLE_GROUP_OVER_POSSIBLE", "AMBER", any_group_possible, "an axle group is within uncertainty of its limit" if any_group_possible else "axle groups clear with margin"))

    # ---------------------------------------------------------------- identity rules
    conflict = identity.method == "conflict"
    rules.append(RuleResult("IDENTITY_CONFLICT", "RED", conflict, "ANPR plate and RFID tag resolve to different vehicles (possible cloning)" if conflict else "no identity conflict"))
    unknown = vehicle is None
    rules.append(RuleResult("VEHICLE_UNKNOWN", "AMBER", unknown, "vehicle not registered on the platform" if unknown else f"vehicle {vehicle.plate} registered"))
    low_conf = (not unknown) and identity.confidence < identity_min_confidence
    rules.append(RuleResult("IDENTITY_LOW_CONFIDENCE", "AMBER", low_conf, f"identity confidence {identity.confidence:.2f} < {identity_min_confidence}" if low_conf else "identity confidence sufficient"))

    if vehicle is not None:
        expected = vehicle.axle_config if not vehicle.trailer_axle_config else f"{vehicle.axle_config}+{vehicle.trailer_axle_config}"
        mismatch = parse_axle_config(expected) != parse_axle_config(m.detected_axle_config) if m.detected_axle_config else False
        rules.append(RuleResult("AXLE_CONFIG_MISMATCH", "AMBER", mismatch, f"detected {m.detected_axle_config} vs registered {expected}" if mismatch else "axle configuration matches registration"))
        wl = bool(vehicle.watchlist_reason)
        rules.append(RuleResult("WATCHLIST", "RED", wl, f"vehicle on watch-list: {vehicle.watchlist_reason}" if wl else "not on watch-list"))

    # ---------------------------------------------------------------- cargo rules
    breached = cargo.seal_status in ("breached", "removed")
    rules.append(RuleResult("SEAL_BREACH", "RED", breached, f"electronic seal status {cargo.seal_status}" if breached else "seal intact or not applicable"))
    if vehicle is not None and cargo.declared_mass_kg:
        expected_gvm = vehicle.tare_kg + cargo.declared_mass_kg
        diff = m.gvm_kg - expected_gvm
        tol = max(0.15 * expected_gvm, m.gvm_u_kg)
        big = abs(diff) > 2 * tol
        mid = abs(diff) > tol and not big
        margins["declaration"] = {"expected_gvm_kg": expected_gvm, "diff_kg": round(diff), "tolerance_kg": round(tol)}
        rules.append(RuleResult("DECLARATION_MISMATCH_LARGE", "RED", big, f"measured GVM differs from declaration by {diff:+.0f} kg (> {2*tol:.0f})" if big else "no large declaration mismatch"))
        rules.append(RuleResult("DECLARATION_MISMATCH", "AMBER", mid, f"measured GVM differs from declaration by {diff:+.0f} kg" if mid else "declaration consistent"))
    if cargo.vgm_kg and vehicle is not None:
        diff = m.gvm_kg - (vehicle.tare_kg + cargo.vgm_kg)
        over = diff > max(0.05 * cargo.vgm_kg, m.gvm_u_kg)
        rules.append(RuleResult("VGM_MISMATCH", "AMBER", over, f"GVM exceeds tare+VGM by {diff:.0f} kg" if over else "consistent with VGM"))
    if cargo.anomaly_score is not None:
        hi = cargo.anomaly_score >= 0.8
        rules.append(RuleResult("CARGO_ANOMALY_ADVISORY", "AMBER", hi, f"cargo anomaly score {cargo.anomaly_score:.2f} (advisory AI)" if hi else "no cargo anomaly"))

    # ---------------------------------------------------------------- random audit (seeded, logged)
    seed = audit_seed if audit_seed is not None else random.SystemRandom().randrange(2**31)
    audit = random.Random(seed).random() < audit_rate
    rules.append(RuleResult("RANDOM_AUDIT", "AMBER", audit, f"selected for random audit (rate {audit_rate:.1%}, seed {seed})" if audit else "not selected for audit"))

    # ---------------------------------------------------------------- resolve
    fired = [r for r in rules if r.fired]
    if any(r.severity == "RED" for r in fired):
        decision: Decision = "RED"
    elif any(r.severity == "AMBER" for r in fired):
        decision = "AMBER"
    else:
        decision = "GREEN"

    if decision == "GREEN":
        explanation = (
            f"GREEN: GVM {m.gvm_kg:.0f} kg ± {m.gvm_u_kg:.0f} kg is within {gvm_tol:.0f} kg with margin; all axle groups within limits; "
            f"identity {identity.method} at {identity.confidence:.2f}; measurement quality acceptable. Source: {m.source}."
        )
    else:
        explanation = f"{decision}: " + "; ".join(r.detail for r in fired if r.severity != "INFO") + f". Source: {m.source}."

    evidence = {
        "engine": ENGINE_VERSION,
        "limits": limits.version,
        "measurement": asdict(m),
        "identity": asdict(identity),
        "vehicle": asdict(vehicle) if vehicle else None,
        "cargo": asdict(cargo),
        "rules": [asdict(r) for r in rules],
        "decision": decision,
        "audit_seed": seed,
    }
    evidence_hash = hashlib.sha256(json.dumps(evidence, sort_keys=True, default=str).encode()).hexdigest()
    return ClearanceResult(decision, rules, margins, explanation, evidence_hash, audit, seed, limits.version)
