"""Predictive Release Agent (Module 6): estimates when a shipment will be released, with P10/P50/P90 and reasons.

Model: stage-duration model. Each remaining stage has a lognormal duration whose parameters come from historical
completed shipments on the platform (if >= 20 samples per stage) or from documented priors (hours):
    declared -> at_port 6 (sigma .6) | at_port -> customs 12 (.7) | customs -> weighing 8 (.8) | weighing -> gate 3 (.5) | gate -> released 2 (.5)
Multipliers: congestion (station utilisation), declaration missing (+24 h, blocks), seal unknown (+6 h),
warehouse not ready (+12 h at the end), AMBER/RED last decision (+4 h / +24 h). Monte-Carlo (2000 draws) gives quantiles.
No government data is consulted unless an authorised adapter is in `real` mode and supplies stage events.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar

import numpy as np

from .base import Agent

STAGES = ["registered", "declared", "at_port", "customs_processing", "weighing_verification", "gate_processing", "released"]
PRIORS_H = {  # (median hours, sigma of log)
    "registered": (2.0, 0.5),
    "declared": (6.0, 0.6),
    "at_port": (12.0, 0.7),
    "customs_processing": (8.0, 0.8),
    "weighing_verification": (3.0, 0.5),
    "gate_processing": (2.0, 0.5),
}


class ReleasePredictionAgent(Agent):
    name: ClassVar[str] = "release_predictor"
    version: ClassVar[str] = "0.2"
    responsibilities: ClassVar[str] = "Predict cargo release time (P10/P50/P90) from current stage, outstanding requirements, congestion and history; explain delays."
    inputs: ClassVar[dict[str, str]] = {
        "stage": "current stage",
        "now": "datetime",
        "has_declaration": "bool",
        "seal_status": "optional armed|breached|unknown|None",
        "station_utilisation": "optional 0..1",
        "warehouse_ready": "optional bool",
        "last_decision": "optional GREEN|AMBER|RED",
        "history": "optional {stage: [durations_h]} from completed shipments",
    }
    outputs: ClassVar[dict[str, str]] = {"p10": "iso", "p50": "iso", "p90": "iso", "reasons": "list", "stage_estimates_h": "dict"}

    def _run(self, inputs: dict[str, Any]):
        stage = inputs["stage"]
        now: datetime = inputs.get("now") or datetime.now(UTC)
        hist = inputs.get("history") or {}
        rng = np.random.default_rng(0)
        reasons: list[str] = []
        warnings: list[str] = []
        if stage in ("released", "in_transit", "delivered", "closed"):
            return {"p10": now.isoformat(), "p50": now.isoformat(), "p90": now.isoformat(), "reasons": ["already released"], "stage_estimates_h": {}}, 0.95, "shipment already released", []
        idx = STAGES.index(stage) if stage in STAGES else 0
        remaining = STAGES[idx:-1]
        draws = np.zeros(2000)
        est: dict[str, float] = {}
        util = float(inputs.get("station_utilisation") or 0.0)
        cong = 1.0 + 1.5 * max(0.0, util - 0.6)  # above 60 % utilisation processing stretches
        if cong > 1.05:
            reasons.append(f"station utilisation {util:.0%} adds ~{(cong-1)*100:.0f}% to weighing/gate stages")
        used_history = 0
        for st in remaining:
            med, sig = PRIORS_H.get(st, (4.0, 0.6))
            samples = hist.get(st)
            if samples and len(samples) >= 20:
                arr = np.log(np.clip(np.array(samples, dtype=float), 0.1, None))
                med, sig = float(np.exp(np.median(arr))), float(max(0.2, arr.std()))
                used_history += 1
            mult = cong if st in ("weighing_verification", "gate_processing", "at_port") else 1.0
            d = rng.lognormal(np.log(med * mult), sig, size=2000)
            draws += d
            est[st] = round(med * mult, 1)
        if not inputs.get("has_declaration", True):
            draws += 24.0
            reasons.append("cargo declaration missing: +24 h (blocking)")
        if inputs.get("seal_status") in ("unknown", None) and idx >= 2:
            draws += 6.0
            reasons.append("electronic seal status unknown: +6 h")
        if inputs.get("seal_status") == "breached":
            draws += 48.0
            reasons.append("seal breached: inspection, +48 h")
        if inputs.get("warehouse_ready") is False:
            draws += 12.0
            reasons.append("destination warehouse not ready: +12 h")
        ld = inputs.get("last_decision")
        if ld == "AMBER":
            draws += 4.0
            reasons.append("last weighing AMBER: static verification +4 h")
        elif ld == "RED":
            draws += 24.0
            reasons.append("last weighing RED: inspection +24 h")
        p10, p50, p90 = (now + timedelta(hours=float(np.quantile(draws, q))) for q in (0.1, 0.5, 0.9))
        if used_history == 0:
            warnings.append("no platform history yet: using documented priors")
        conf = 0.35 + 0.1 * used_history
        return ({"p10": p10.isoformat(), "p50": p50.isoformat(), "p90": p90.isoformat(), "reasons": reasons, "stage_estimates_h": est, "remaining_stages": remaining},
                conf, f"{len(remaining)} stages remaining; median {float(np.quantile(draws, 0.5)):.1f} h", warnings)
