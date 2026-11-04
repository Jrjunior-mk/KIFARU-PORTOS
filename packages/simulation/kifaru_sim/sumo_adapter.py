"""Optional SUMO (Simulation of Urban MObility) integration.

SUMO is a microscopic road-traffic simulator. The SimPy model here is a queueing model of the *station*; SUMO adds the
*approach road*: platooning, overtaking, merging from two lanes into the weighbridge exit and the resulting bunching of
arrivals. The integration is deliberately loose:

1. ``export_inputs`` writes a ``.rou.xml`` of truck departures from the SimPy arrival profile, netconvert node/edge
   files and a minimal ``.net.xml`` of the Mariakani approach (two through lanes + weighbridge exit lane) plus a
   ``.sumocfg``.
2. If SUMO is installed, ``run_sumo`` runs it and ``read_sumo_arrivals`` parses the ``tripinfo`` output (vehicle
   arrival times at the weighbridge edge).
3. ``replay_into_model`` feeds those arrival times into the SimPy model instead of the Poisson generator.

When SUMO / TraCI is absent (the normal case on a developer laptop) every entry point degrades gracefully with a clear
message: inputs are still written, nothing crashes.
"""
from __future__ import annotations

import importlib.util
import shutil
import subprocess
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .model import SimConfig, SimResult, generate_arrivals, run_model

APPROACH_LENGTH_M = 2000.0  # Mombasa Road approach modelled from 2 km before the station
WEIGH_EXIT_LENGTH_M = 300.0  # deceleration / exit lane into the WIM array
TRUCK_VTYPE = dict(id="hgv", vClass="truck", length="16.5", maxSpeed="22.2", accel="1.0", decel="3.5", sigma="0.5", minGap="3.0")


class SumoUnavailable(RuntimeError):
    pass


@dataclass
class SumoStatus:
    sumo_binary: str | None
    netconvert_binary: str | None
    traci_importable: bool

    @property
    def available(self) -> bool:
        return self.sumo_binary is not None

    @property
    def message(self) -> str:
        if self.available:
            return f"SUMO available: {self.sumo_binary} (traci {'importable' if self.traci_importable else 'not importable'})"
        return (
            "SUMO is not installed (no 'sumo' binary on PATH and 'traci' not importable). The SimPy model runs standalone; "
            "SUMO inputs can still be exported. Install from https://sumo.dlr.de and set SUMO_HOME to enable the micro-simulation path."
        )


def sumo_status() -> SumoStatus:
    return SumoStatus(shutil.which("sumo") or shutil.which("sumo.exe"), shutil.which("netconvert"), importlib.util.find_spec("traci") is not None)


# ------------------------------------------------------------------------------------------------- writers
def write_route_file(arrivals_s: np.ndarray, path: Path, approach_speed_mps: float = 20.0) -> Path:
    """Departures are shifted earlier by the free-flow travel time so that free-flow arrival = SimPy arrival."""
    travel = (APPROACH_LENGTH_M + WEIGH_EXIT_LENGTH_M) / approach_speed_mps
    root = ET.Element("routes")
    ET.SubElement(root, "vType", **TRUCK_VTYPE)
    ET.SubElement(root, "route", id="to_weighbridge", edges="approach weigh_exit")
    for i, t in enumerate(sorted(float(x) for x in arrivals_s)):
        ET.SubElement(root, "vehicle", id=f"truck{i:05d}", type="hgv", route="to_weighbridge", depart=f"{max(0.0, t - travel):.1f}", departLane="best", departSpeed="max")
    ET.indent(root)
    path.write_text(ET.tostring(root, encoding="unicode", xml_declaration=True), encoding="utf-8")
    return path


def write_netconvert_inputs(out: Path) -> tuple[Path, Path]:
    """Node/edge files for `netconvert` — the supported way to obtain a fully valid network."""
    nodes = ET.Element("nodes")
    ET.SubElement(nodes, "node", id="n_start", x="0", y="0", type="priority")
    ET.SubElement(nodes, "node", id="n_split", x=f"{APPROACH_LENGTH_M:.0f}", y="0", type="priority")
    ET.SubElement(nodes, "node", id="n_weigh", x=f"{APPROACH_LENGTH_M + WEIGH_EXIT_LENGTH_M:.0f}", y="-8", type="priority")
    ET.SubElement(nodes, "node", id="n_through", x=f"{APPROACH_LENGTH_M + WEIGH_EXIT_LENGTH_M:.0f}", y="0", type="priority")
    edges = ET.Element("edges")
    ET.SubElement(edges, "edge", id="approach", **{"from": "n_start", "to": "n_split", "numLanes": "2", "speed": "22.2", "name": "Mombasa Rd approach (A109)"})
    ET.SubElement(edges, "edge", id="weigh_exit", **{"from": "n_split", "to": "n_weigh", "numLanes": "1", "speed": "11.1", "name": "Mariakani weighbridge exit / WIM array"})
    ET.SubElement(edges, "edge", id="through", **{"from": "n_split", "to": "n_through", "numLanes": "2", "speed": "22.2", "name": "through lanes (light vehicles)"})
    ET.indent(nodes)
    ET.indent(edges)
    nod, edg = out / "mariakani.nod.xml", out / "mariakani.edg.xml"
    nod.write_text(ET.tostring(nodes, encoding="unicode", xml_declaration=True), encoding="utf-8")
    edg.write_text(ET.tostring(edges, encoding="unicode", xml_declaration=True), encoding="utf-8")
    return nod, edg


def write_minimal_net(path: Path) -> Path:
    """A minimal hand-written .net.xml (two approach lanes + weighbridge exit). Sufficient for SUMO to load a
    straight-line network; for anything richer regenerate with `netconvert -n mariakani.nod.xml -e mariakani.edg.xml`."""
    L1, L2 = APPROACH_LENGTH_M, WEIGH_EXIT_LENGTH_M
    x1, x2 = L1, L1 + L2
    net = ET.Element("net", version="1.16", junctionCornerDetail="5", limitTurnSpeed="5.50")
    ET.SubElement(net, "location", netOffset="0.00,0.00", convBoundary=f"0.00,-8.00,{x2:.2f},3.20", origBoundary="-10000000000.00,-10000000000.00,10000000000.00,10000000000.00", projParameter="!")
    e = ET.SubElement(net, "edge", id="approach", **{"from": "n_start", "to": "n_split", "priority": "1"})
    ET.SubElement(e, "lane", id="approach_0", index="0", speed="22.20", length=f"{L1:.2f}", shape=f"0.00,-1.60 {x1:.2f},-1.60")
    ET.SubElement(e, "lane", id="approach_1", index="1", speed="22.20", length=f"{L1:.2f}", shape=f"0.00,1.60 {x1:.2f},1.60")
    e = ET.SubElement(net, "edge", id="weigh_exit", **{"from": "n_split", "to": "n_weigh", "priority": "1"})
    ET.SubElement(e, "lane", id="weigh_exit_0", index="0", speed="11.10", length=f"{L2:.2f}", shape=f"{x1:.2f},-1.60 {x2:.2f},-8.00")
    e = ET.SubElement(net, "edge", id="through", **{"from": "n_split", "to": "n_through", "priority": "1"})
    ET.SubElement(e, "lane", id="through_0", index="0", speed="22.20", length=f"{L2:.2f}", shape=f"{x1:.2f},-1.60 {x2:.2f},-1.60")
    ET.SubElement(e, "lane", id="through_1", index="1", speed="22.20", length=f"{L2:.2f}", shape=f"{x1:.2f},1.60 {x2:.2f},1.60")
    ET.SubElement(net, "junction", id="n_start", type="dead_end", x="0.00", y="0.00", incLanes="", intLanes="", shape="0.00,3.20 0.00,-3.20")
    ET.SubElement(net, "junction", id="n_split", type="priority", x=f"{x1:.2f}", y="0.00", incLanes="approach_0 approach_1", intLanes="", shape=f"{x1:.2f},3.20 {x1:.2f},-3.20")
    ET.SubElement(net, "junction", id="n_weigh", type="dead_end", x=f"{x2:.2f}", y="-8.00", incLanes="weigh_exit_0", intLanes="", shape=f"{x2:.2f},-6.40 {x2:.2f},-9.60")
    ET.SubElement(net, "junction", id="n_through", type="dead_end", x=f"{x2:.2f}", y="0.00", incLanes="through_0 through_1", intLanes="", shape=f"{x2:.2f},3.20 {x2:.2f},-3.20")
    ET.SubElement(net, "connection", **{"from": "approach", "to": "weigh_exit", "fromLane": "0", "toLane": "0", "dir": "r", "state": "M"})
    ET.SubElement(net, "connection", **{"from": "approach", "to": "through", "fromLane": "0", "toLane": "0", "dir": "s", "state": "M"})
    ET.SubElement(net, "connection", **{"from": "approach", "to": "through", "fromLane": "1", "toLane": "1", "dir": "s", "state": "M"})
    ET.indent(net)
    path.write_text(ET.tostring(net, encoding="unicode", xml_declaration=True), encoding="utf-8")
    return path


def write_sumocfg(out: Path, net: Path, routes: Path, end_s: float) -> Path:
    cfg = ET.Element("configuration")
    inp = ET.SubElement(cfg, "input")
    ET.SubElement(inp, "net-file", value=net.name)
    ET.SubElement(inp, "route-files", value=routes.name)
    tm = ET.SubElement(cfg, "time")
    ET.SubElement(tm, "begin", value="0")
    ET.SubElement(tm, "end", value=f"{end_s:.0f}")
    o = ET.SubElement(cfg, "output")
    ET.SubElement(o, "tripinfo-output", value="tripinfo.xml")
    ET.indent(cfg)
    p = out / "mariakani.sumocfg"
    p.write_text(ET.tostring(cfg, encoding="unicode", xml_declaration=True), encoding="utf-8")
    return p


def export_inputs(cfg: SimConfig, out_dir) -> dict[str, str]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    arrivals = generate_arrivals(cfg, np.random.default_rng(cfg.seed))
    rou = write_route_file(arrivals, out / "mariakani_trucks.rou.xml")
    nod, edg = write_netconvert_inputs(out)
    net = write_minimal_net(out / "mariakani.net.xml")
    sumocfg = write_sumocfg(out, net, rou, cfg.horizon_s + 3600)
    return {"routes": str(rou), "nodes": str(nod), "edges": str(edg), "net": str(net), "sumocfg": str(sumocfg), "n_trucks": str(len(arrivals))}


# ------------------------------------------------------------------------------------------------- running
def run_sumo(sumocfg: Path, timeout_s: int = 600) -> Path:
    st = sumo_status()
    if not st.available:
        raise SumoUnavailable(st.message)
    subprocess.run([st.sumo_binary, "-c", str(sumocfg), "--no-step-log", "--no-warnings"], check=True, cwd=sumocfg.parent, timeout=timeout_s)
    return sumocfg.parent / "tripinfo.xml"


def read_sumo_arrivals(tripinfo_xml: Path, edge: str = "weigh_exit") -> np.ndarray:
    """Arrival times (s) of vehicles that finished on the weighbridge edge, from SUMO's tripinfo output."""
    root = ET.parse(tripinfo_xml).getroot()
    out = []
    for ti in root.iter("tripinfo"):
        if edge and not ti.get("arrivalLane", "").startswith(edge):
            continue
        a = ti.get("arrival")
        if a is not None and float(a) >= 0:
            out.append(float(a))
    return np.sort(np.array(out))


def replay_into_model(cfg: SimConfig, arrivals_s: np.ndarray) -> SimResult:
    """Run the SimPy station model with externally supplied (e.g. SUMO-induced) arrival times."""
    arrivals = np.sort(np.asarray(arrivals_s, dtype=float))
    horizon = float(arrivals.max()) + 1.0 if len(arrivals) else cfg.horizon_s
    return run_model(cfg.with_overrides(hours=max(cfg.hours, horizon / 3600.0)), arrivals=arrivals)


def run_with_sumo(cfg: SimConfig, work_dir) -> SimResult:
    """Full chain: export -> sumo -> parse -> replay. Raises SumoUnavailable with a clear message if SUMO is absent."""
    paths = export_inputs(cfg, work_dir)
    tripinfo = run_sumo(Path(paths["sumocfg"]))
    return replay_into_model(cfg, read_sumo_arrivals(tripinfo))
