"""Scenario comparison report: K replications per scenario, 95 % confidence intervals, Markdown + JSON output.

All figures are MODELLED (synthetic arrivals, assumed service distributions). Fuel and CO2 come from
``kifaru_ai_agents.environmental.EnvironmentalAgent`` and are labelled modelled estimates.
"""
from __future__ import annotations

import json
import math
import platform
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime

import numpy as np
from scipy import stats

from kifaru_ai_agents.environmental import EnvironmentalAgent

from . import scenarios as scn
from .model import SimConfig, SimResult, run_model

CI_LEVEL = 0.95

METRIC_COLUMNS: list[tuple[str, str, str]] = [
    # key, header, format
    ("trucks", "Trucks", "{:.0f}"),
    ("mean_tis_min", "Mean time in system (min)", "{:.1f}"),
    ("p90_tis_min", "P90 time in system (min)", "{:.1f}"),
    ("mean_queue_static", "Mean static queue", "{:.1f}"),
    ("max_queue_static", "Max static queue", "{:.0f}"),
    ("pct_stopped", "% trucks stopped", "{:.1f}"),
    ("static_utilisation_pct", "Static-scale utilisation (%)", "{:.0f}"),
    ("stops_avoided_vs_baseline", "Stops avoided vs baseline", "{:.0f}"),
    ("fuel_l_modelled", "Fuel, modelled (L)", "{:.0f}"),
    ("co2_kg_modelled", "CO2, modelled (kg)", "{:.0f}"),
]


@dataclass
class Summary:
    mean: float
    ci_low: float
    ci_high: float
    n: int

    def fmt(self, f: str) -> str:
        if self.n <= 1 or math.isnan(self.ci_low):
            return f.format(self.mean)
        half = (self.ci_high - self.ci_low) / 2
        return f"{f.format(self.mean)} ± {f.format(half)}"


@dataclass
class ScenarioOutcome:
    name: str
    description: str
    config: dict
    replications: list[dict]
    summary: dict[str, Summary]
    decision_mix: dict[str, float]
    queue_series_mean: list[float] = field(default_factory=list)  # mean static queue by minute across reps


def ci(values: list[float] | np.ndarray, level: float = CI_LEVEL) -> Summary:
    arr = np.asarray(values, dtype=float)
    n = len(arr)
    m = float(arr.mean()) if n else float("nan")
    if n < 2:
        return Summary(m, float("nan"), float("nan"), n)
    se = float(arr.std(ddof=1)) / math.sqrt(n)
    t = float(stats.t.ppf(0.5 + level / 2, n - 1))
    return Summary(m, m - t * se, m + t * se, n)


def modelled_environment(metrics: dict) -> dict:
    """Fuel/CO2 for the trucks that stopped in this scenario (modelled; EnvironmentalAgent factors)."""
    res = EnvironmentalAgent().run({"stops_avoided": metrics["n_not_stopped"], "stops_made": metrics["n_stopped"], "avg_queue_wait_s": metrics["mean_wait_static_s"], "empty_km": 0.0})
    if not res.ok:
        return {"litres": float("nan"), "co2_kg": float("nan"), "label": res.error or "agent failed"}
    plat = res.output["platform"]
    return {"litres": plat["litres"], "co2_kg": plat["co2_kg"], "cost_kes": plat["cost_kes"], "label": res.output["label"], "factors": res.output["factors"]}


def run_replications(name: str, hours: float, reps: int, base_seed: int, base: SimConfig = scn.BASE, overrides: dict | None = None) -> tuple[list[SimResult], SimConfig]:
    results = []
    cfg0 = scn.build(name, base=base, hours=hours, seed=base_seed, **(overrides or {}))
    for k in range(reps):
        cfg = cfg0.with_overrides(seed=base_seed + k)
        results.append(run_model(cfg))
    return results, cfg0


def compare(names: list[str], hours: float = 12.0, reps: int = 5, base_seed: int = 1000, base: SimConfig = scn.BASE, overrides: dict | None = None, baseline: str = "baseline_all_stop") -> dict:
    """Runs every scenario (always including the baseline) and returns the comparison structure."""
    t_start = time.perf_counter()
    order = list(dict.fromkeys([baseline, *names])) if baseline in scn.SCENARIOS else list(names)
    per_rep_metrics: dict[str, list[dict]] = {}
    cfgs: dict[str, SimConfig] = {}
    series: dict[str, list[np.ndarray]] = {}
    for name in order:
        results, cfg = run_replications(name, hours, reps, base_seed, base=base, overrides=overrides)
        cfgs[name] = cfg
        rows = []
        for r in results:
            m = r.metrics()
            m["static_utilisation_pct"] = 100.0 * m["static_utilisation"]
            env = modelled_environment(m)
            m["fuel_l_modelled"], m["co2_kg_modelled"] = env["litres"], env["co2_kg"]
            m["seed"] = r.config.seed
            rows.append(m)
        per_rep_metrics[name] = rows
        series[name] = [r.queue_static for r in results]

    # stops avoided vs baseline: paired by replication (same seed index)
    base_rows = per_rep_metrics.get(baseline)
    outcomes: dict[str, ScenarioOutcome] = {}
    for name in order:
        rows = per_rep_metrics[name]
        for i, row in enumerate(rows):
            if base_rows is not None and i < len(base_rows):
                row["stops_avoided_vs_baseline"] = base_rows[i]["n_stopped"] - row["n_stopped"]
                row["fuel_saved_vs_baseline_l_modelled"] = base_rows[i]["fuel_l_modelled"] - row["fuel_l_modelled"]
                row["co2_saved_vs_baseline_kg_modelled"] = base_rows[i]["co2_kg_modelled"] - row["co2_kg_modelled"]
            else:
                row["stops_avoided_vs_baseline"] = float("nan")
        keys = [k for k in rows[0] if isinstance(rows[0][k], (int, float)) and k != "seed"]
        summary = {k: ci([r[k] for r in rows]) for k in keys}
        mix = {d: float(np.mean([r[f"pct_{d.lower()}"] for r in rows])) for d in ("GREEN", "AMBER", "RED")}
        n_min = min(len(s) for s in series[name])
        qmean = np.mean([s[:n_min] for s in series[name]], axis=0).tolist() if n_min else []
        cfg_d = asdict(cfgs[name])
        cfg_d["limits"] = cfgs[name].limits.version
        outcomes[name] = ScenarioOutcome(name, scn.DESCRIPTIONS.get(name, ""), cfg_d, rows, summary, mix, qmean)

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "hours": hours,
        "replications": reps,
        "base_seed": base_seed,
        "baseline": baseline,
        "ci_level": CI_LEVEL,
        "runtime_s": round(time.perf_counter() - t_start, 1),
        "python": platform.python_version(),
        "label": "MODELLED RESULTS — synthetic arrivals and assumed service-time distributions; not measured field data.",
        "outcomes": outcomes,
    }


# ------------------------------------------------------------------------------------------------- rendering
def to_json(cmp: dict) -> str:
    def enc(o):
        if isinstance(o, Summary):
            return {"mean": o.mean, "ci_low": o.ci_low, "ci_high": o.ci_high, "n": o.n}
        if isinstance(o, ScenarioOutcome):
            return {"name": o.name, "description": o.description, "config": o.config, "replications": o.replications, "summary": o.summary, "decision_mix": o.decision_mix, "static_queue_mean_by_minute": o.queue_series_mean}
        if isinstance(o, (np.floating, np.integer)):
            return o.item()
        if isinstance(o, float) and math.isnan(o):
            return None
        return str(o)

    return json.dumps(cmp, default=enc, indent=2)


def _nan_safe(s: Summary, f: str) -> str:
    if math.isnan(s.mean):
        return "—"
    return s.fmt(f)


def to_markdown(cmp: dict) -> str:
    outcomes: dict[str, ScenarioOutcome] = cmp["outcomes"]
    lines = [
        "# KIFARU PORTOS — scenario comparison (modelled)",
        "",
        f"Generated {cmp['generated_at']} · horizon {cmp['hours']:g} h · {cmp['replications']} replications per scenario · "
        f"base seed {cmp['base_seed']} · {int(cmp['ci_level']*100)} % confidence intervals (Student t) · runtime {cmp['runtime_s']} s",
        "",
        f"> **{cmp['label']}** Fuel and CO2 are modelled estimates from the Environmental agent factors "
        "(idle 2.5 L/h, 0.35 L per stop-start cycle, 2.68 kg CO2/L) and must not be reported as measured savings. "
        "Baseline data is to be collected in Phase 7 before any claim is made.",
        "",
        "## Comparison table",
        "",
    ]
    headers = ["Scenario", *[h for _, h, _ in METRIC_COLUMNS], "GREEN / AMBER / RED (%)"]
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("|" + "---|" * len(headers))
    for name, o in outcomes.items():
        cells = [f"`{name}`"]
        for key, _, f in METRIC_COLUMNS:
            s = o.summary.get(key)
            cells.append(_nan_safe(s, f) if s else "—")
        mix = o.decision_mix
        cells.append(f"{mix['GREEN']:.0f} / {mix['AMBER']:.0f} / {mix['RED']:.0f}")
        lines.append("| " + " | ".join(cells) + " |")
    lines += ["", "Values are mean ± half-width of the 95 % CI across replications. "
              "P90 of a heavy-tailed distribution can be below the mean when a few inspected trucks dominate the mean.", ""]

    lines += ["## Secondary metrics", "", "| Scenario | Mean WIM queue | Max WIM queue | Mean static wait of stopped trucks (s) | Inspection-bay utilisation (%) | P90 time in system, priority cargo (min) | Fuel saved vs baseline, modelled (L) | CO2 saved vs baseline, modelled (kg) | Drain after last arrival (min) |", "|---|---|---|---|---|---|---|---|---|"]
    for name, o in outcomes.items():
        s = o.summary
        lines.append(
            f"| `{name}` | {_nan_safe(s['mean_queue_wim'], '{:.2f}')} | {_nan_safe(s['max_queue_wim'], '{:.0f}')} | {_nan_safe(s['mean_wait_static_s'], '{:.0f}')} | "
            f"{s['inspection_utilisation'].mean*100:.0f} | {_nan_safe(s['p90_tis_priority_min'], '{:.1f}')} | "
            f"{_nan_safe(s.get('fuel_saved_vs_baseline_l_modelled', Summary(float('nan'), 0, 0, 0)), '{:.0f}')} | "
            f"{_nan_safe(s.get('co2_saved_vs_baseline_kg_modelled', Summary(float('nan'), 0, 0, 0)), '{:.0f}')} | {_nan_safe(s['drain_min'], '{:.0f}')} |"
        )
    lines += ["", "## Scenario definitions", ""]
    for name, o in outcomes.items():
        c = o.config
        lines.append(
            f"- `{name}` — {o.description} (policy={c['policy']}, arrivals/h={c['arrivals_per_hour']}×{c['arrival_multiplier']}, WIM lanes={c['wim_lanes']}, "
            f"static bays={c['static_bays']}, inspection bays={c['inspection_bays']}, inspection rate={c['inspection_rate']}, audit rate={c['audit_rate']}, "
            f"slot cap/15 min={c['slot_cap_per_15min']}, priority queue={c['priority_queue']}, hold prob={c['release_hold_prob']}, lane failures={c['lane_failures']})"
        )
    lines += [
        "",
        "## Method and limitations",
        "",
        "- Discrete-event model (SimPy): non-homogeneous Poisson arrivals with a synthetic hour-of-day profile; lognormal service times "
        "(WIM median 6 s, static scale median 4 min, inspection median 25 min); truck masses from `kifaru_wim_dsp.signal_gen.random_truck`; "
        "decisions from the deterministic clearance engine `kifaru.services.clearance_engine.decide` (same code as the platform).",
        "- The baseline scenario is a modelled all-stop station, not an observed one. No field baseline data exists yet (Phase 7).",
        "- Identity confidence, sensor-fault rates and the overload share are assumptions (see config of each scenario).",
        "- Replications differ only by random seed; CIs describe simulation variance, not model-structure uncertainty.",
        "",
    ]
    return "\n".join(lines)


def write_report(cmp: dict, out_dir, stem: str = "scenario-comparison") -> tuple[str, str]:
    from pathlib import Path

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    md, js = out / f"{stem}.md", out / f"{stem}.json"
    md.write_text(to_markdown(cmp), encoding="utf-8")
    js.write_text(to_json(cmp), encoding="utf-8")
    return str(md), str(js)
