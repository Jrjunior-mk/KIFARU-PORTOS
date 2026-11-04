"""The remaining cooperating agents (Module 9): weighing intelligence, vehicle identity, queue optimisation,
cargo verification (anomaly), security & anomaly, operational incident. All advisory; all explainable."""
from __future__ import annotations

from typing import Any, ClassVar

import numpy as np

from .base import Agent


class WeighingIntelligenceAgent(Agent):
    name: ClassVar[str] = "weighing_intelligence"
    version: ClassVar[str] = "0.2"
    responsibilities: ClassVar[str] = "Assess measurement plausibility: cross-row consistency, speed/dynamic effects, temperature drift; recommend quality flags."
    inputs: ClassVar[dict[str, str]] = {"measurement": "WimMeasurement.to_dict()", "recent_measurements": "optional list of previous measurement dicts on this lane"}
    outputs: ClassVar[dict[str, str]] = {"plausible": "bool", "suggested_flags": "list", "row_bias": "{row: relative bias}"}

    def _run(self, inputs: dict[str, Any]):
        m = inputs["measurement"]
        flags: list[str] = []
        row_bias: dict[str, float] = {}
        rows: dict[str, list[float]] = {}
        for a in m.get("axles", []):
            for r, v in a.get("per_row_kg", {}).items():
                rows.setdefault(r, []).append(float(v) / max(1.0, float(a["load_kg"])))
        for r, vals in rows.items():
            row_bias[r] = round(float(np.mean(vals)) - 1.0, 4)
            if abs(row_bias[r]) > 0.08:
                flags.append(f"row_bias:{r}")
        if m.get("speed_mps", 0) > 25:
            flags.append("high_speed_dynamic_effect")
        if m.get("pavement_temp_c", 25) > 55:
            flags.append("pavement_temp_extreme")
        recent = inputs.get("recent_measurements") or []
        if len(recent) >= 10:
            gvms = np.array([float(x["gvm_kg"]) for x in recent])
            if m["gvm_kg"] > gvms.mean() + 4 * gvms.std(ddof=1):
                flags.append("gvm_outlier_vs_lane_history")
        plausible = not any(f.startswith("row_bias") for f in flags)
        conf = 0.85 if rows else 0.4
        return {"plausible": plausible, "suggested_flags": flags, "row_bias": row_bias}, conf, ("measurement plausible" if plausible else "cross-row bias suggests a drifting sensor"), []


class VehicleIdentityAgent(Agent):
    name: ClassVar[str] = "vehicle_identity"
    version: ClassVar[str] = "0.2"
    responsibilities: ClassVar[str] = "Fuse ANPR and RFID evidence into a vehicle identity with confidence; detect conflicts (possible tag cloning / plate tampering)."
    inputs: ClassVar[dict[str, str]] = {"anpr_plate": "optional", "anpr_confidence": "optional", "rfid_epc": "optional", "rfid_confidence": "optional",
                                        "anpr_vehicle_id": "optional resolved id", "rfid_vehicle_id": "optional resolved id"}
    outputs: ClassVar[dict[str, str]] = {"vehicle_id": "fused id or null", "confidence": "0..1", "method": "rfid+anpr|rfid|anpr|none|conflict"}

    def _run(self, inputs: dict[str, Any]):
        av, rv = inputs.get("anpr_vehicle_id"), inputs.get("rfid_vehicle_id")
        ca, cr = float(inputs.get("anpr_confidence") or 0), float(inputs.get("rfid_confidence") or 0)
        if av and rv:
            if av == rv:
                c = 1 - (1 - ca) * (1 - cr)
                return {"vehicle_id": av, "confidence": c, "method": "rfid+anpr"}, c, "ANPR and RFID agree", []
            return {"vehicle_id": None, "confidence": 0.0, "method": "conflict"}, 0.9, "ANPR and RFID resolve to different vehicles", ["possible cloned tag or swapped plate"]
        if rv:
            return {"vehicle_id": rv, "confidence": min(cr, 0.95), "method": "rfid"}, min(cr, 0.95), "RFID only", ["single-source identity capped at 0.95"]
        if av:
            return {"vehicle_id": av, "confidence": min(ca, 0.95), "method": "anpr"}, min(ca, 0.95), "ANPR only", ["single-source identity capped at 0.95"]
        return {"vehicle_id": None, "confidence": 0.0, "method": "none"}, 0.9, "no evidence", []


class QueueOptimizationAgent(Agent):
    name: ClassVar[str] = "queue_optimizer"
    version: ClassVar[str] = "0.2"
    responsibilities: ClassVar[str] = "Recommend slot windows and (where permitted) alternative stations to flatten predicted queues; respect cargo priority."
    inputs: ClassVar[dict[str, str]] = {"stations": "list of {station_id, code, alt_allowed, capacity_per_hour, forecast: {h: queue_len}, distance_km}",
                                        "requests": "list of {vehicle_id, priority(1-9), earliest_min}"}
    outputs: ClassVar[dict[str, str]] = {"assignments": "[{vehicle_id, station_id, slot_offset_min, expected_wait_min, reason}]"}

    def _run(self, inputs: dict[str, Any]):
        stations = inputs["stations"]
        reqs = sorted(inputs["requests"], key=lambda r: (r.get("priority", 5), r.get("earliest_min", 0)))
        load: dict[tuple[str, int], int] = {}
        out = []
        primary = stations[0] if stations else None
        for r in reqs:
            best = None
            for st in stations:
                if st is not primary and not st.get("alt_allowed", False):
                    continue
                cap15 = max(1, int(st["capacity_per_hour"] / 4))
                for off in range(int(r.get("earliest_min", 0)) // 15 * 15, 240, 15):
                    key = (st["station_id"], off)
                    fq = st.get("forecast", {}).get(str(min(120, max(15, off))), 0)
                    if load.get(key, 0) < cap15:
                        wait = fq / max(1, st["capacity_per_hour"]) * 60 + (st.get("distance_km", 0) / 45 * 60)
                        cand = (wait + off * 0.2, st, off, wait)
                        if best is None or cand[0] < best[0]:
                            best = cand
                        break
            if best is None:
                out.append({"vehicle_id": r["vehicle_id"], "station_id": None, "slot_offset_min": None, "expected_wait_min": None, "reason": "no capacity within 4 h"})
                continue
            _, st, off, wait = best
            load[(st["station_id"], off)] = load.get((st["station_id"], off), 0) + 1
            why = "primary station" if st is primary else f"authorised alternative {st['code']} (alt_allowed)"
            out.append({"vehicle_id": r["vehicle_id"], "station_id": st["station_id"], "slot_offset_min": off, "expected_wait_min": round(wait), "reason": f"{why}; priority {r.get('priority', 5)}"})
        return {"assignments": out}, 0.7, f"assigned {sum(1 for a in out if a['station_id'])}/{len(out)} requests", []


class CargoVerificationAgent(Agent):
    name: ClassVar[str] = "cargo_verification"
    version: ClassVar[str] = "0.2"
    responsibilities: ClassVar[str] = "Score cargo/vehicle discrepancies: measured vs declared mass, VGM, seal status, container-vehicle compatibility; output an anomaly score for the clearance engine (advisory)."
    inputs: ClassVar[dict[str, str]] = {"gvm_kg": "measured", "tare_kg": "vehicle tare", "declared_mass_kg": "optional", "vgm_kg": "optional",
                                        "seal_status": "optional", "cargo_type": "optional", "body_type": "optional", "containers": "optional count"}
    outputs: ClassVar[dict[str, str]] = {"anomaly_score": "0..1", "signals": "list"}

    def _run(self, inputs: dict[str, Any]):
        score, signals = 0.0, []
        payload = float(inputs["gvm_kg"]) - float(inputs["tare_kg"])
        dec = inputs.get("declared_mass_kg")
        if dec:
            rel = abs(payload - dec) / max(1.0, dec)
            if rel > 0.15:
                score += min(0.6, rel)
                signals.append(f"payload {payload:.0f} kg vs declared {dec} kg ({rel:.0%})")
        vgm = inputs.get("vgm_kg")
        if vgm and payload > vgm * 1.05:
            score += 0.3
            signals.append(f"payload exceeds VGM {vgm} kg by >5 %")
        if inputs.get("seal_status") in ("breached", "removed"):
            score += 0.8
            signals.append(f"seal {inputs['seal_status']}")
        ct, bt = inputs.get("cargo_type"), inputs.get("body_type")
        compat = {"liquid": {"tanker"}, "reefer": {"reefer"}, "container": {"container", "flatbed"}}
        if ct in compat and bt and bt not in compat[ct]:
            score += 0.4
            signals.append(f"cargo type {ct} on {bt} body")
        if inputs.get("containers", 0) and inputs.get("containers", 0) > 2:
            score += 0.2
            signals.append("more than two containers declared for one truck")
        score = min(1.0, score)
        return {"anomaly_score": round(score, 3), "signals": signals}, 0.7, (f"anomaly {score:.2f}: " + "; ".join(signals)) if signals else "no cargo anomaly signals", []


class SecurityAnomalyAgent(Agent):
    name: ClassVar[str] = "security_anomaly"
    version: ClassVar[str] = "0.2"
    responsibilities: ClassVar[str] = "Detect suspicious operational patterns: repeated identity conflicts, impossible travel (same tag at two stations too fast), override bursts, login anomalies."
    inputs: ClassVar[dict[str, str]] = {"events": "list of {type, ts(datetime), station_id?, plate?, epc?, user_id?, lat?, lon?}"}
    outputs: ClassVar[dict[str, str]] = {"alerts": "[{kind, severity, detail}]"}

    def _run(self, inputs: dict[str, Any]):
        from .base import haversine_km

        evs = sorted(inputs["events"], key=lambda e: e["ts"])
        alerts = []
        conflicts = [e for e in evs if e.get("type") == "identity_conflict"]
        by_plate: dict[str, int] = {}
        for e in conflicts:
            by_plate[e.get("plate") or "?"] = by_plate.get(e.get("plate") or "?", 0) + 1
        for plate, n in by_plate.items():
            if n >= 2:
                alerts.append({"kind": "repeated_identity_conflict", "severity": "high", "detail": f"{plate}: {n} ANPR/RFID conflicts"})
        last_seen: dict[str, dict] = {}
        for e in evs:
            epc = e.get("epc")
            if not epc or e.get("lat") is None:
                continue
            prev = last_seen.get(epc)
            if prev:
                km = haversine_km(prev["lat"], prev["lon"], e["lat"], e["lon"])
                h = (e["ts"] - prev["ts"]).total_seconds() / 3600
                if h > 0 and km / h > 120:
                    alerts.append({"kind": "impossible_travel", "severity": "critical", "detail": f"tag {epc}: {km:.0f} km in {h*60:.0f} min (possible cloning)"})
            last_seen[epc] = e
        overrides = [e for e in evs if e.get("type") == "override"]
        by_user: dict[str, int] = {}
        for e in overrides:
            by_user[e.get("user_id") or "?"] = by_user.get(e.get("user_id") or "?", 0) + 1
        for u, n in by_user.items():
            if n >= 3:
                alerts.append({"kind": "override_burst", "severity": "high", "detail": f"user {u}: {n} overrides in window"})
        fails = [e for e in evs if e.get("type") == "login_failed"]
        if len(fails) >= 10:
            alerts.append({"kind": "credential_stuffing", "severity": "medium", "detail": f"{len(fails)} failed logins in window"})
        return {"alerts": alerts}, 0.75, f"{len(alerts)} alerts", []


class OperationalIncidentAgent(Agent):
    name: ClassVar[str] = "operational_incident"
    version: ClassVar[str] = "0.2"
    responsibilities: ClassVar[str] = "Turn sensor-health, station-status and queue signals into prioritised incident recommendations with suggested actions."
    inputs: ClassVar[dict[str, str]] = {"sensor_health": "{sensor: ok|degraded|fault}", "station_status": "operational|degraded|offline", "queue_len": "int", "capacity_per_hour": "int", "forecast_120_queue": "optional int"}
    outputs: ClassVar[dict[str, str]] = {"incidents": "[{severity, category, title, action}]"}

    def _run(self, inputs: dict[str, Any]):
        inc = []
        faults = [k for k, v in inputs.get("sensor_health", {}).items() if v == "fault"]
        degraded = [k for k, v in inputs.get("sensor_health", {}).items() if v == "degraded"]
        if faults:
            inc.append({"severity": "high", "category": "sensor_fault", "title": f"Sensor fault: {', '.join(faults)}", "action": "Lane to AMBER-only pre-screen; dispatch maintenance; verify with static scale"})
        if degraded:
            inc.append({"severity": "medium", "category": "sensor_fault", "title": f"Sensor degraded: {', '.join(degraded)}", "action": "Schedule calibration check; monitor cross-row bias"})
        if inputs.get("station_status") == "offline":
            inc.append({"severity": "critical", "category": "station_failure", "title": "Station offline", "action": "Divert to authorised alternative station; notify transporters with booked slots"})
        cap = max(1, int(inputs.get("capacity_per_hour", 120)))
        q = int(inputs.get("queue_len", 0))
        if q > cap:
            inc.append({"severity": "high", "category": "traffic", "title": f"Queue {q} exceeds hourly capacity {cap}", "action": "Open additional lane; raise GREEN pass-through; reschedule low-priority slots"})
        f120 = inputs.get("forecast_120_queue")
        if f120 and f120 > cap * 1.5:
            inc.append({"severity": "medium", "category": "traffic", "title": f"Forecast queue {f120} in 2 h", "action": "Pre-emptively offer alternative-station slots to inbound trucks"})
        return {"incidents": inc}, 0.7, f"{len(inc)} recommendations", []
