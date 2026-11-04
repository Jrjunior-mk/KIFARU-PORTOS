"""Backhaul Matching Agent (Module 4, BKH-02).

Deterministic, explainable scoring of (offer, truck) pairs. The score is a weighted sum of normalised criteria; every
component is returned so a dispatcher can see WHY a match ranks where it does. The agent only *proposes*; assignment
requires acceptance by both the transporter and the cargo owner (BKH-04).

Economics defaults (overridable per call, all documented in docs/06-operations/emissions-model.md):
  fuel consumption loaded   : 0.42 L/km (6-7 axle articulated, Northern Corridor average)
  fuel consumption empty    : 0.30 L/km
  diesel price              : 170 KES/L  (configuration; update from current pump price)
  CO2 factor diesel         : 2.68 kg CO2 per litre
  driver max remaining hours: 9 h/day (configurable)
  average speed             : 45 km/h
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, ClassVar

from .base import ROAD_FACTOR, Agent, haversine_km

DEFAULT_ECON = {
    "fuel_l_per_km_loaded": 0.42,
    "fuel_l_per_km_empty": 0.30,
    "diesel_kes_per_l": 170.0,
    "co2_kg_per_l": 2.68,
    "avg_speed_kmh": 45.0,
    "driver_max_remaining_h": 9.0,
}

BODY_COMPAT = {
    "general": {"flatbed", "box", "container"},
    "container": {"container", "flatbed"},
    "bulk": {"tipper", "flatbed"},
    "liquid": {"tanker"},
    "reefer": {"reefer"},
    "hazardous": {"tanker", "box"},
}


class BackhaulMatchingAgent(Agent):
    name: ClassVar[str] = "backhaul_matcher"
    version: ClassVar[str] = "0.2"
    responsibilities: ClassVar[str] = "Rank available trucks for a return-cargo offer by extra distance, capacity fit, deadline, fuel, driver hours and revenue; explain each score."
    inputs: ClassVar[dict[str, str]] = {
        "offer": "{mass_kg, volume_m3?, cargo_type, origin_lat, origin_lon, dest_lat, dest_lon, ready_from, deadline, offered_price_kes, requires_body_types?}",
        "trucks": "list of {vehicle_id, payload_capacity_kg, body_type, lat, lon, home_lat, home_lon, driver_hours_used_h?, available_from?}",
        "econ": "optional overrides of DEFAULT_ECON",
    }
    outputs: ClassVar[dict[str, str]] = {"matches": "ranked list of {vehicle_id, score, extra_km, fuel_litres, fuel_cost_kes, revenue_kes, co2_avoided_kg, feasible, explanation}"}

    def _run(self, inputs: dict[str, Any]):
        offer = inputs["offer"]
        trucks = inputs["trucks"]
        econ = {**DEFAULT_ECON, **(inputs.get("econ") or {})}
        warnings: list[str] = []
        matches = []
        load_km = haversine_km(offer["origin_lat"], offer["origin_lon"], offer["dest_lat"], offer["dest_lon"]) * ROAD_FACTOR
        for t in trucks:
            exp: dict[str, Any] = {}
            feasible = True
            reasons: list[str] = []
            # --- capacity
            cap = float(t.get("payload_capacity_kg", 0))
            fit = offer["mass_kg"] / cap if cap > 0 else 9.9
            exp["capacity_fit"] = round(fit, 3)
            if fit > 1.0:
                feasible = False
                reasons.append(f"cargo {offer['mass_kg']} kg exceeds payload capacity {cap:.0f} kg")
            # --- body compatibility
            required = set(offer.get("requires_body_types") or []) or BODY_COMPAT.get(offer.get("cargo_type", "general"), {"flatbed"})
            compatible = t.get("body_type") in required
            exp["body_compatible"] = compatible
            if not compatible:
                feasible = False
                reasons.append(f"body type {t.get('body_type')} not in {sorted(required)}")
            # --- distances
            to_pickup = haversine_km(t["lat"], t["lon"], offer["origin_lat"], offer["origin_lon"]) * ROAD_FACTOR
            home_lat, home_lon = t.get("home_lat", t["lat"]), t.get("home_lon", t["lon"])
            direct_home = haversine_km(t["lat"], t["lon"], home_lat, home_lon) * ROAD_FACTOR
            dest_to_home = haversine_km(offer["dest_lat"], offer["dest_lon"], home_lat, home_lon) * ROAD_FACTOR
            with_cargo = to_pickup + load_km + dest_to_home
            extra_km = max(0.0, with_cargo - direct_home)
            exp.update({"km_to_pickup": round(to_pickup, 1), "km_loaded": round(load_km, 1), "km_direct_home": round(direct_home, 1), "extra_km": round(extra_km, 1)})
            # --- time / deadline / driver hours
            hours_needed = with_cargo / econ["avg_speed_kmh"] + 1.5  # +1.5 h loading/unloading
            avail = t.get("available_from") or offer["ready_from"]
            start = max(avail, offer["ready_from"]) if isinstance(avail, datetime) else offer["ready_from"]
            eta = start + timedelta(hours=hours_needed)
            meets_deadline = eta <= offer["deadline"]
            exp["eta"] = eta.isoformat()
            exp["meets_deadline"] = meets_deadline
            if not meets_deadline:
                feasible = False
                reasons.append(f"ETA {eta:%Y-%m-%d %H:%M} after deadline {offer['deadline']:%Y-%m-%d %H:%M}")
            remaining_h = econ["driver_max_remaining_h"] - float(t.get("driver_hours_used_h", 0.0))
            exp["driver_hours_needed"] = round(hours_needed, 1)
            exp["driver_hours_remaining_today"] = round(remaining_h, 1)
            if hours_needed > remaining_h:
                reasons.append("requires a rest period (driver hours)")
            # --- economics
            fuel_l = to_pickup * econ["fuel_l_per_km_empty"] + load_km * econ["fuel_l_per_km_loaded"] + dest_to_home * econ["fuel_l_per_km_empty"]
            fuel_l_direct = direct_home * econ["fuel_l_per_km_empty"]
            fuel_extra_l = max(0.0, fuel_l - fuel_l_direct)
            fuel_cost = fuel_extra_l * econ["diesel_kes_per_l"]
            revenue = float(offer["offered_price_kes"])
            margin = revenue - fuel_cost
            # emissions avoided vs a dedicated truck doing a round trip for this cargo (loaded out, empty back)
            dedicated_l = load_km * econ["fuel_l_per_km_loaded"] + load_km * econ["fuel_l_per_km_empty"]
            co2_avoided = max(0.0, dedicated_l - fuel_extra_l) * econ["co2_kg_per_l"]
            exp.update({"fuel_extra_l": round(fuel_extra_l, 1), "fuel_cost_kes": round(fuel_cost), "revenue_kes": round(revenue), "margin_kes": round(margin), "co2_avoided_kg": round(co2_avoided)})
            # --- score (0..1)
            s_dist = max(0.0, 1.0 - extra_km / 300.0)
            s_fit = 1.0 - abs(0.85 - min(fit, 1.0)) / 0.85  # best when ~85 % utilised
            s_margin = max(0.0, min(1.0, margin / max(1.0, revenue)))
            s_time = 1.0 if meets_deadline else 0.0
            s_hours = 1.0 if hours_needed <= remaining_h else 0.5
            score = 0.35 * s_dist + 0.2 * s_fit + 0.25 * s_margin + 0.1 * s_time + 0.1 * s_hours
            if not feasible:
                score *= 0.1
            exp["score_components"] = {"distance": round(s_dist, 2), "capacity": round(s_fit, 2), "margin": round(s_margin, 2), "deadline": s_time, "driver_hours": s_hours}
            matches.append({"vehicle_id": t["vehicle_id"], "score": round(score, 4), "extra_km": round(extra_km, 1), "fuel_litres": round(fuel_extra_l, 1),
                            "fuel_cost_kes": round(fuel_cost, 2), "revenue_kes": round(revenue, 2), "co2_avoided_kg": round(co2_avoided, 1), "feasible": feasible,
                            "reasons": reasons, "explanation": exp})
        matches.sort(key=lambda m: (-m["feasible"], -m["score"]))
        n_feasible = sum(1 for m in matches if m["feasible"])
        if n_feasible == 0:
            warnings.append("no feasible truck for this offer")
        conf = 0.8 if n_feasible else 0.3
        return {"matches": matches, "feasible_count": n_feasible, "econ": econ}, conf, f"{n_feasible}/{len(matches)} trucks feasible; ranked by distance, fit, margin, deadline, hours", warnings
