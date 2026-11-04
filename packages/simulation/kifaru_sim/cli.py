"""``kifaru-sim`` command line.

    kifaru-sim list
    kifaru-sim run --scenarios all --hours 12 --reps 5 --out reports/
    kifaru-sim run --scenarios rolling_clearance,arrivals_+50 --set arrivals_per_hour=60 --set static_bays=4
    kifaru-sim sumo-export --out sumo/ --hours 12
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import fields

from . import scenarios as scn
from .model import SimConfig
from .report import compare, to_markdown, write_report


def _parse_set(items: list[str] | None) -> dict:
    out: dict = {}
    types = {f.name: f.type for f in fields(SimConfig)}
    for item in items or []:
        if "=" not in item:
            raise SystemExit(f"--set expects key=value, got '{item}'")
        k, v = item.split("=", 1)
        if k not in types:
            raise SystemExit(f"unknown SimConfig field '{k}'. Fields: {', '.join(sorted(types))}")
        t = str(types[k])
        if "bool" in t:
            out[k] = v.lower() in ("1", "true", "yes")
        elif "int" in t and "float" not in t:
            out[k] = int(v)
        elif "float" in t:
            out[k] = float(v)
        else:
            out[k] = v
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="kifaru-sim", description="KIFARU PORTOS weighing-station scenario simulator (SimPy). All results are modelled.")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="list scenarios")
    r = sub.add_parser("run", help="run scenarios and write a comparison report")
    r.add_argument("--scenarios", default="all", help="comma-separated scenario names or 'all'")
    r.add_argument("--hours", type=float, default=12.0)
    r.add_argument("--reps", type=int, default=5)
    r.add_argument("--seed", type=int, default=1000)
    r.add_argument("--out", default="reports/")
    r.add_argument("--stem", default="scenario-comparison")
    r.add_argument("--set", action="append", default=[], help="override a SimConfig field for every scenario, key=value")
    r.add_argument("--quiet", action="store_true")
    s = sub.add_parser("sumo-export", help="write SUMO route/network inputs for the arrival profile (SUMO itself optional)")
    s.add_argument("--out", default="sumo/")
    s.add_argument("--hours", type=float, default=12.0)
    s.add_argument("--seed", type=int, default=1000)
    s.add_argument("--set", action="append", default=[])
    a = p.parse_args(argv)

    if a.cmd == "list":
        for name in scn.list_scenarios():
            print(f"{name:26s} {scn.DESCRIPTIONS.get(name, '')}")
        return 0
    if a.cmd == "sumo-export":
        from .sumo_adapter import export_inputs, sumo_status

        cfg = scn.BASE.with_overrides(hours=a.hours, seed=a.seed, **_parse_set(a.set))
        paths = export_inputs(cfg, a.out)
        print(sumo_status().message)
        for k, v in paths.items():
            print(f"{k:12s} {v}")
        return 0

    names = scn.list_scenarios() if a.scenarios == "all" else [x.strip() for x in a.scenarios.split(",") if x.strip()]
    unknown = [n for n in names if n not in scn.SCENARIOS]
    if unknown:
        raise SystemExit(f"unknown scenario(s): {unknown}. Use 'kifaru-sim list'.")
    cmp = compare(names, hours=a.hours, reps=a.reps, base_seed=a.seed, overrides=_parse_set(a.set))
    md, js = write_report(cmp, a.out, stem=a.stem)
    if not a.quiet:
        print(to_markdown(cmp))
    print(f"\nwritten: {md}\nwritten: {js}", file=sys.stderr)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
