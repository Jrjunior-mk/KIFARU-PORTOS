from __future__ import annotations

import json
import xml.etree.ElementTree as ET

import numpy as np
import pytest

from kifaru_sim.cli import main
from kifaru_sim.model import SimConfig, generate_arrivals
from kifaru_sim.report import ci, compare, to_json, to_markdown, write_report
from kifaru_sim.sumo_adapter import SumoUnavailable, export_inputs, read_sumo_arrivals, replay_into_model, run_sumo, sumo_status


def test_ci_helper():
    s = ci([10.0, 12.0, 11.0, 13.0])
    assert s.n == 4 and s.ci_low < s.mean < s.ci_high
    assert "±" in s.fmt("{:.1f}")
    assert ci([5.0]).fmt("{:.0f}") == "5"


def test_report_renders_markdown_and_json(tmp_path):
    cmp = compare(["rolling_clearance", "arrivals_+20"], hours=3, reps=2, base_seed=5)
    md = to_markdown(cmp)
    assert "baseline_all_stop" in md and "rolling_clearance" in md and "arrivals_+20" in md
    assert "MODELLED" in md and "modelled" in md.lower()
    assert "| Scenario |" in md and "Stops avoided vs baseline" in md
    data = json.loads(to_json(cmp))
    o = data["outcomes"]["rolling_clearance"]
    assert o["summary"]["pct_stopped"]["mean"] < 100 and o["summary"]["stops_avoided_vs_baseline"]["mean"] > 0
    assert data["outcomes"]["baseline_all_stop"]["summary"]["pct_stopped"]["mean"] == 100.0
    assert "fuel_l_modelled" in o["summary"] and "co2_kg_modelled" in o["summary"]
    assert len(o["replications"]) == 2 and o["replications"][0]["seed"] == 5
    md_path, js_path = write_report(cmp, tmp_path, stem="t")
    assert (tmp_path / "t.md").exists() and (tmp_path / "t.json").exists()


def test_cli_list_and_run(tmp_path, capsys):
    assert main(["list"]) == 0
    assert "rolling_clearance" in capsys.readouterr().out
    rc = main(["run", "--scenarios", "rolling_clearance", "--hours", "2", "--reps", "1", "--out", str(tmp_path), "--set", "arrivals_per_hour=30", "--quiet"])
    assert rc == 0
    data = json.loads((tmp_path / "scenario-comparison.json").read_text(encoding="utf-8"))
    assert data["outcomes"]["rolling_clearance"]["config"]["arrivals_per_hour"] == 30.0
    with pytest.raises(SystemExit):
        main(["run", "--scenarios", "nope"])


def test_sumo_adapter_degrades_gracefully_and_exports(tmp_path):
    st = sumo_status()
    assert isinstance(st.message, str) and len(st.message) > 20
    cfg = SimConfig(hours=1, seed=3)
    paths = export_inputs(cfg, tmp_path)
    routes = ET.parse(paths["routes"]).getroot()
    vehicles = routes.findall("vehicle")
    assert len(vehicles) == int(paths["n_trucks"]) > 10
    assert vehicles[0].get("route") == "to_weighbridge"
    net = ET.parse(paths["net"]).getroot()
    assert {e.get("id") for e in net.findall("edge")} == {"approach", "weigh_exit", "through"}
    assert len(net.find("edge[@id='approach']").findall("lane")) == 2
    ET.parse(paths["sumocfg"])
    if not st.available:
        with pytest.raises(SumoUnavailable) as e:
            run_sumo(tmp_path / "mariakani.sumocfg")
        assert "not installed" in str(e.value)


def test_replay_external_arrivals_and_parse_tripinfo(tmp_path):
    cfg = SimConfig(hours=2, seed=9)
    arrivals = generate_arrivals(cfg, np.random.default_rng(9))
    res = replay_into_model(cfg, arrivals)
    assert len(res.trucks) == len(arrivals)
    assert np.allclose(sorted(t.arrival_s for t in res.trucks), np.sort(arrivals))
    # synthetic tripinfo as SUMO would write it
    root = ET.Element("tripinfos")
    for i, t in enumerate(arrivals[:5]):
        ET.SubElement(root, "tripinfo", id=f"truck{i}", depart="0.0", arrival=f"{t + 100:.1f}", arrivalLane="weigh_exit_0")
    ET.SubElement(root, "tripinfo", id="car", depart="0.0", arrival="50.0", arrivalLane="through_0")
    p = tmp_path / "tripinfo.xml"
    p.write_text(ET.tostring(root, encoding="unicode"), encoding="utf-8")
    parsed = read_sumo_arrivals(p)
    assert len(parsed) == 5 and np.allclose(parsed, np.sort(arrivals[:5]) + 100, atol=0.06)
