"""Model-level tests: conservation, policy effects, determinism."""
from __future__ import annotations

import math

import numpy as np
import pytest

from kifaru_sim import scenarios as scn
from kifaru_sim.model import SimConfig, apply_slot_cap, generate_arrivals, run_model, tod_rate

HOURS = 6.0


def _run(name: str, seed: int = 7, hours: float = HOURS, **kw):
    return run_model(scn.build(name, hours=hours, seed=seed, **kw))


def test_every_truck_exits_and_records_are_complete():
    r = _run("rolling_clearance")
    assert len(r.trucks) > 50
    for t in r.trucks:
        assert not math.isnan(t.exit_s) and t.exit_s >= t.arrival_s
        assert t.decision in ("GREEN", "AMBER", "RED")
        assert t.wait_wim_s >= 0 and t.wait_static_s >= 0
    # trucks that never stopped have no static wait; stopped trucks were AMBER/RED or sampled/held
    for t in r.trucks:
        if not t.stopped:
            assert t.decision == "GREEN" and t.wait_static_s == 0
    assert r.queue_static.min() >= 0 and len(r.series_t_s) >= HOURS * 60


def test_baseline_stops_everyone_and_rolling_reduces_stops():
    base = _run("baseline_all_stop").metrics()
    roll = _run("rolling_clearance").metrics()
    assert base["pct_stopped"] == 100.0
    assert roll["pct_stopped"] < 50.0
    assert roll["mean_tis_min"] < base["mean_tis_min"]
    assert roll["static_utilisation"] < base["static_utilisation"]


def test_green_amber_red_mix_is_plausible():
    m = _run("rolling_clearance", seed=3).metrics()
    assert 50 < m["pct_green"] < 95
    assert m["pct_amber"] > 0 and m["pct_red"] > 0
    assert abs(m["pct_green"] + m["pct_amber"] + m["pct_red"] - 100.0) < 1e-6


def test_plus_50_percent_arrivals_increases_p90_wait_in_baseline_configuration():
    # the +50 % effect is clearest where the static scale is the bottleneck: compare all-stop at 1.0 vs 1.5 demand
    a = run_model(SimConfig(policy="all_stop", hours=HOURS, seed=5)).metrics()
    b = run_model(SimConfig(policy="all_stop", hours=HOURS, seed=5, arrival_multiplier=1.5)).metrics()
    assert b["trucks"] > a["trucks"] * 1.2
    assert b["p90_tis_min"] > a["p90_tis_min"]
    # and under rolling clearance the stopped trucks also wait longer
    c = _run("rolling_clearance", seed=5).metrics()
    d = _run("arrivals_+50", seed=5).metrics()
    assert d["trucks"] > c["trucks"] * 1.2
    assert d["mean_queue_static"] >= c["mean_queue_static"]


def test_lane_failure_increases_static_queue():
    ok = _run("rolling_clearance", seed=11, hours=8).metrics()
    fail = _run("station_lane_failure", seed=11, hours=8).metrics()
    assert fail["pct_stopped"] > ok["pct_stopped"]
    assert fail["max_queue_static"] >= ok["max_queue_static"]
    assert fail["mean_queue_static"] > ok["mean_queue_static"]


def test_static_capacity_minus_one_raises_utilisation():
    ok = _run("rolling_clearance", seed=2).metrics()
    less = _run("static_capacity_-1", seed=2).metrics()
    assert less["static_utilisation"] > ok["static_utilisation"]


def test_delayed_release_and_priority_scenarios_run():
    hold = _run("delayed_cargo_release", seed=4)
    assert any(t.hold_s > 0 for t in hold.trucks)
    assert hold.metrics()["pct_stopped"] > _run("rolling_clearance", seed=4).metrics()["pct_stopped"]
    prio = _run("queue_policy_priority", seed=4)
    assert any(t.priority for t in prio.trucks)
    assert prio.metrics()["p90_tis_priority_min"] >= 0


def test_determinism_with_fixed_seed():
    a = _run("arrivals_+20", seed=42)
    b = _run("arrivals_+20", seed=42)
    assert [t.arrival_s for t in a.trucks] == [t.arrival_s for t in b.trucks]
    assert [t.exit_s for t in a.trucks] == [t.exit_s for t in b.trucks]
    assert [t.decision for t in a.trucks] == [t.decision for t in b.trucks]
    assert a.metrics() == b.metrics()
    c = _run("arrivals_+20", seed=43)
    assert c.metrics() != a.metrics()


def test_time_of_day_profile_and_slot_cap():
    cfg = SimConfig(hours=24, seed=1)
    rates = [tod_rate(cfg, h * 3600) for h in range(24)]
    assert max(rates) > 1.3 * cfg.arrivals_per_hour and min(rates) < 0.5 * cfg.arrivals_per_hour
    rng = np.random.default_rng(0)
    arr = generate_arrivals(cfg, rng)
    assert 0.8 * 24 * cfg.arrivals_per_hour < len(arr) < 1.2 * 24 * cfg.arrivals_per_hour
    capped = apply_slot_cap(arr, cap=10, rng=np.random.default_rng(0))
    assert len(capped) == len(arr)
    counts = np.bincount((capped // 900).astype(int))
    assert counts.max() <= 10
    assert np.all(np.diff(capped) >= 0)


def test_scenario_registry():
    names = scn.list_scenarios()
    for required in ("baseline_all_stop", "rolling_clearance", "arrivals_+20", "arrivals_+30", "arrivals_+50", "station_lane_failure",
                     "inspection_rate_x2", "static_capacity_-1", "delayed_cargo_release", "dynamic_slot_allocation", "queue_policy_priority"):
        assert required in names
    with pytest.raises(KeyError):
        scn.build("does_not_exist")
    cfg = scn.build("station_lane_failure", hours=10)
    assert cfg.lane_failures and cfg.lane_failures[0][1] == 7200.0
