"""Environmental Intelligence Agent (Module 8).

All outputs are MODELLED estimates, never measurements. Formulas and factors (also in docs/06-operations/emissions-model.md):

  idling fuel (L)        = idle_hours x idle_l_per_h                    idle_l_per_h = 2.5 (heavy diesel, A/C off; range 2-4)
  stop-start penalty (L) = stops x stop_penalty_l                       stop_penalty_l = 0.35 (decelerate from 60 km/h, queue, re-accelerate)
  empty-trip fuel (L)    = empty_km x fuel_l_per_km_empty               0.30 L/km
  detour fuel (L)        = detour_km x fuel_l_per_km_loaded             0.42 L/km
  CO2 (kg)               = litres x 2.68 kg CO2/L (diesel, tank-to-wheel, IPCC/DEFRA order of magnitude)
  cost (KES)             = litres x diesel price (170 KES/L default; configurable)

Savings are computed as (baseline scenario) - (platform scenario) and labelled "modelled".
"""
from __future__ import annotations

from typing import Any, ClassVar

from .base import Agent

FACTORS = {
    "idle_l_per_h": 2.5,
    "stop_penalty_l": 0.35,
    "fuel_l_per_km_empty": 0.30,
    "fuel_l_per_km_loaded": 0.42,
    "co2_kg_per_l": 2.68,
    "diesel_kes_per_l": 170.0,
}


class EnvironmentalAgent(Agent):
    name: ClassVar[str] = "environmental"
    version: ClassVar[str] = "0.2"
    responsibilities: ClassVar[str] = "Estimate fuel, cost and CO2 from idling, stops, empty km and detours; compute modelled savings vs baseline."
    inputs: ClassVar[dict[str, str]] = {
        "stops_avoided": "number of trucks cleared without stopping (GREEN)",
        "stops_made": "number of trucks that stopped (AMBER+RED or baseline)",
        "avg_queue_wait_s": "average wait per stopping truck",
        "empty_km": "empty kilometres (baseline)",
        "empty_km_avoided": "optional empty km avoided by backhaul matches",
        "detour_km": "optional unnecessary detour km",
        "factors": "optional overrides of FACTORS",
    }
    outputs: ClassVar[dict[str, str]] = {"baseline": "{litres, co2_kg, cost_kes}", "platform": "{...}", "savings": "{...}", "factors": "used", "label": "modelled"}

    def _run(self, inputs: dict[str, Any]):
        f = {**FACTORS, **(inputs.get("factors") or {})}
        avoided = float(inputs.get("stops_avoided", 0))
        made = float(inputs.get("stops_made", 0))
        wait_h = float(inputs.get("avg_queue_wait_s", 0)) / 3600.0
        empty_km = float(inputs.get("empty_km", 0))
        empty_avoided = float(inputs.get("empty_km_avoided", 0))
        detour_km = float(inputs.get("detour_km", 0))

        def bundle(stops: float, idle_h: float, e_km: float, d_km: float) -> dict:
            idle_l = idle_h * f["idle_l_per_h"]
            stop_l = stops * f["stop_penalty_l"]
            empty_l = e_km * f["fuel_l_per_km_empty"]
            detour_l = d_km * f["fuel_l_per_km_loaded"]
            litres = idle_l + stop_l + empty_l + detour_l
            return {"idle_l": round(idle_l, 1), "stop_l": round(stop_l, 1), "empty_l": round(empty_l, 1), "detour_l": round(detour_l, 1),
                    "litres": round(litres, 1), "co2_kg": round(litres * f["co2_kg_per_l"], 1), "cost_kes": round(litres * f["diesel_kes_per_l"])}

        # baseline: every truck stops (avoided + made) and waits; all empty km driven; detours driven
        baseline = bundle(avoided + made, (avoided + made) * wait_h, empty_km, detour_km)
        platform = bundle(made, made * wait_h, max(0.0, empty_km - empty_avoided), 0.0)
        savings = {k: round(baseline[k] - platform[k], 1) for k in ("litres", "co2_kg", "cost_kes")}
        return ({"baseline": baseline, "platform": platform, "savings": savings, "factors": f, "label": "modelled estimate — not a measured result",
                 "assumptions": ["each avoided stop saves one deceleration/queue/acceleration cycle", "idle consumption 2.5 L/h", "diesel 2.68 kg CO2/L tank-to-wheel"]},
                0.6, f"modelled: {savings['litres']:.0f} L and {savings['co2_kg']:.0f} kg CO2 avoided vs all-stop baseline", ["outputs are modelled, not measured"])
