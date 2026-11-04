"""Queue forecasting (TRQ-01) — thin wrapper around the Traffic Prediction Agent plus a queueing-theory fallback.

Horizons: 15, 30, 60, 120 minutes. When fewer than 8 observations exist the agent cannot fit, so the fallback uses an
M/M/c approximation with the station's capacity: this is clearly labelled model_version="mmc-fallback".
"""
from __future__ import annotations

import math
from datetime import timedelta

from kifaru_ai_agents.traffic_forecast import TrafficForecastAgent

from ..models import QueueRecord, WeighingStation, utcnow

HORIZONS = (15, 30, 60, 120)


def slot_capacity(st: WeighingStation, window_min: int) -> int:
    return max(1, int(st.capacity_per_hour * window_min / 60))


def _mmc_wait_s(arrivals_per_hour: float, capacity_per_hour: float, lanes: int = 2) -> float:
    """Mean wait in queue for M/M/c (Erlang C). Service rate per lane = capacity/lanes."""
    if arrivals_per_hour <= 0:
        return 0.0
    mu = max(1e-6, capacity_per_hour / lanes)
    lam = arrivals_per_hour
    rho = lam / (lanes * mu)
    if rho >= 0.98:
        return 3600.0  # saturated: cap at 1 h for display
    a = lam / mu
    s = sum(a**k / math.factorial(k) for k in range(lanes))
    last = a**lanes / (math.factorial(lanes) * (1 - rho))
    p_wait = last / (s + last)
    wq = p_wait / (lanes * mu - lam)  # hours
    return wq * 3600.0


def forecast_station(st: WeighingStation, history: list[QueueRecord]) -> list[QueueRecord]:
    now = utcnow()
    out: list[QueueRecord] = []
    agent = TrafficForecastAgent()
    series = [{"ts": r.ts, "queue_len": r.queue_len, "arrivals_per_hour": r.arrivals_per_hour, "avg_wait_s": r.avg_wait_s} for r in history]
    res = agent.run({"series": series, "horizons_min": list(HORIZONS), "capacity_per_hour": st.capacity_per_hour, "now": now})
    lanes = max(1, len([l for l in st.lanes if l.type != "static"]))
    for h in HORIZONS:
        f = res.output["forecasts"][str(h)]
        arrivals = f["arrivals_per_hour"]
        wait = _mmc_wait_s(arrivals, st.capacity_per_hour, lanes)
        out.append(
            QueueRecord(
                station_id=st.id,
                ts=now + timedelta(minutes=h),
                kind=f"forecast_{h}",
                queue_len=int(round(f["queue_len"])),
                avg_wait_s=int(round(wait)),
                utilisation=min(1.0, arrivals / max(1, st.capacity_per_hour)),
                arrivals_per_hour=float(arrivals),
                lower=int(round(f["queue_len_lower"])),
                upper=int(round(f["queue_len_upper"])),
                model_version=res.output["model_version"],
                source="forecast",
            )
        )
    return out
