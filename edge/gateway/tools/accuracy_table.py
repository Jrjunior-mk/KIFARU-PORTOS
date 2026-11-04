"""Build the truth-vs-measured accuracy table (lab rig §8 / calibration §6) from gateway logs.

  python tools/accuracy_table.py --input runs.jsonl [--truth truth.csv]

`runs.jsonl`: one JSON object per pass as logged by the gateway ("pass {...}" lines, or the `weighing.completed`
payloads); when the simulator is used the `truth` field is embedded, otherwise `truth.csv` maps pass_id -> truth GVM
and axle loads. Output: Markdown table with n, mean error, s, 95 % half-width, reported U and fraction |err| <= U.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict


def load_runs(path: str) -> list[dict]:
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if line.startswith("{"):
                out.append(json.loads(line))
            elif "pass {" in line:
                out.append(json.loads(line[line.index("{"):]))
    return out


def load_truth(path: str | None) -> dict[int, dict]:
    if not path:
        return {}
    truth = {}
    with open(path, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            truth[int(row["pass_id"])] = {"gvm_kg": float(row["gvm_kg"]), "axle_loads_kg": [float(x) for x in row.get("axle_loads_kg", "").split("|") if x]}
    return truth


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--truth")
    ap.add_argument("--group-by", default="axle_config", help="field used for table rows (e.g. axle_config, speed bin)")
    a = ap.parse_args()
    runs, truth = load_runs(a.input), load_truth(a.truth)
    groups: dict[str, list[tuple[float, float, float]]] = defaultdict(list)
    for r in runs:
        payload = r.get("payload", r)
        ingest = payload.get("ingest", {})
        m = ingest.get("measurement", {}) if ingest else {}
        gvm = m.get("gvm_kg", r.get("gvm_kg"))
        u = m.get("gvm_u_kg", r.get("gvm_u_kg"))
        t = (payload.get("truth") or {}).get("gvm_kg") or r.get("truth_gvm_kg") or truth.get(int(r.get("pass_id", -1)), {}).get("gvm_kg")
        if gvm is None or u is None or not t:
            continue
        key = m.get("axle_config", r.get("axle_config", "?")) if a.group_by == "axle_config" else str(r.get(a.group_by, "?"))
        groups[key].append((float(t), float(gvm), float(u)))
    print("| group | n | mean truth (kg) | mean meas (kg) | mean err (%) | s (%) | 95 % half-width (%) | mean U reported (kg) | frac |err| <= U |")
    print("|---|---|---|---|---|---|---|---|---|")
    for key in sorted(groups):
        rows = groups[key]
        n = len(rows)
        errs = [(m - t) / t * 100 for t, m, _ in rows]
        mean_err = sum(errs) / n
        s = math.sqrt(sum((e - mean_err) ** 2 for e in errs) / (n - 1)) if n > 1 else float("nan")
        within = sum(1 for t, m, u in rows if abs(m - t) <= u) / n
        print(f"| {key} | {n} | {sum(t for t, _, _ in rows) / n:.0f} | {sum(m for _, m, _ in rows) / n:.0f} | {mean_err:+.2f} | {s:.2f} | {1.96 * s:.2f} | {sum(u for _, _, u in rows) / n:.0f} | {within:.2f} |")
    print("\nSynthetic/simulated inputs produce synthetic tables: label them as such. This script never certifies accuracy.")


if __name__ == "__main__":
    main()
