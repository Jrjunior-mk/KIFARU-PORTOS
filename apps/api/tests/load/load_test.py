"""Lightweight load test (no external tooling): concurrent HTTP clients against a running API.

Usage:  python tests/load/load_test.py --base http://localhost:8000 --clients 20 --seconds 30
Reports throughput and latency percentiles for: simulate (full lane-pass pipeline incl. DSP + decision + ticket + ledger),
list events, station overview, public ticket verify. Also reports the engine's own decision latency (latency_ms).
Results are LOCAL measurements on the developer machine, not a production benchmark.
"""
from __future__ import annotations

import argparse
import json
import statistics
import threading
import time

import httpx

API = "/api/v1"


def pct(xs, p):
    if not xs:
        return float("nan")
    xs = sorted(xs)
    k = max(0, min(len(xs) - 1, round(p / 100 * (len(xs) - 1))))
    return xs[k]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--clients", type=int, default=10)
    ap.add_argument("--seconds", type=int, default=20)
    ap.add_argument("--out", default=None)
    ap.add_argument("--inprocess", action="store_true", help="start the API in this process (uses KIFARU_* env, seeds the DB)")
    a = ap.parse_args()

    server = None
    if a.inprocess:
        import uvicorn

        from kifaru.main import create_app
        from kifaru.seed import seed

        seed(verbose=False)
        port = int(a.base.rsplit(":", 1)[1])
        server = uvicorn.Server(uvicorn.Config(create_app(), host="127.0.0.1", port=port, log_level="warning"))
        threading.Thread(target=server.run, daemon=True).start()
        for _ in range(100):
            try:
                if httpx.get(f"{a.base}/health", timeout=1).status_code == 200:
                    break
            except Exception:
                time.sleep(0.2)

    with httpx.Client(base_url=a.base, timeout=30) as c:
        from kifaru.seed import DEMO_PASSWORD

        tok = c.post(f"{API}/auth/login", json={"email": "operator@demo.invalid", "password": DEMO_PASSWORD}).json()["access_token"]
        hdr = {"Authorization": f"Bearer {tok}"}
        sts = c.get(f"{API}/stations", headers=hdr).json()
        lane = next(ln for s in sts for ln in s["lanes"] if ln["type"] == "wim_highspeed")
        seed_ev = c.post(f"{API}/weighing/simulate", headers=hdr, json={"lane_id": lane["id"], "count": 1}).json()[0]
        qr = seed_ev["decision"]["qr_token"]

    lat: dict[str, list[float]] = {"simulate": [], "events": [], "stations": [], "verify": []}
    engine_ms: list[int] = []
    errors = {"count": 0}
    stop = time.monotonic() + a.seconds
    lock = threading.Lock()

    def worker(i: int):
        with httpx.Client(base_url=a.base, timeout=60, headers=hdr) as c:
            n = 0
            while time.monotonic() < stop:
                n += 1
                kind = ["simulate", "events", "stations", "verify"][n % 4]
                t0 = time.perf_counter()
                try:
                    if kind == "simulate":
                        r = c.post(f"{API}/weighing/simulate", json={"lane_id": lane["id"], "count": 1, "seed": i * 100000 + n})
                        if r.status_code == 201:
                            with lock:
                                engine_ms.append(r.json()[0]["decision"]["latency_ms"])
                    elif kind == "events":
                        r = c.get(f"{API}/weighing/events?limit=50")
                    elif kind == "stations":
                        r = c.get(f"{API}/stations")
                    else:
                        r = c.get(f"{API}/tickets/verify/{qr}")
                    ok = r.status_code < 400
                except Exception:
                    ok = False
                dt = (time.perf_counter() - t0) * 1000
                with lock:
                    if ok:
                        lat[kind].append(dt)
                    else:
                        errors["count"] += 1

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(a.clients)]
    t_start = time.monotonic()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    elapsed = time.monotonic() - t_start
    total = sum(len(v) for v in lat.values())
    report = {"clients": a.clients, "seconds": round(elapsed, 1), "requests": total, "rps": round(total / elapsed, 1), "errors": errors["count"],
              "latency_ms": {k: {"n": len(v), "p50": round(pct(v, 50), 1), "p95": round(pct(v, 95), 1), "p99": round(pct(v, 99), 1), "max": round(max(v), 1) if v else None} for k, v in lat.items()},
              "engine_decision_latency_ms": {"n": len(engine_ms), "mean": round(statistics.mean(engine_ms), 1) if engine_ms else None, "p95": pct(engine_ms, 95) if engine_ms else None, "max": max(engine_ms) if engine_ms else None},
              "note": "local developer-machine measurement with SQLite; not a production benchmark"}
    print(json.dumps(report, indent=2))
    if a.out:
        with open(a.out, "w") as f:
            json.dump(report, f, indent=2)
    if server is not None:
        server.should_exit = True


if __name__ == "__main__":
    main()
