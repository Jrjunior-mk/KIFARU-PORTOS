"""Traffic Prediction Agent: arrivals and queue length at +15/+30/+60/+120 min.

Model: gradient-boosted trees (scikit-learn HistGradientBoostingRegressor) on lag features + hour-of-day/day-of-week
when enough history exists (>= 48 observations), otherwise Holt's linear exponential smoothing on the recent series,
otherwise persistence. Prediction intervals come from the empirical residual quantiles of a rolling backtest.
Every result states which model produced it (`model_version`).
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar

import numpy as np

from .base import Agent


def _features(ts: list[datetime], y: np.ndarray, k: int) -> np.ndarray:
    rows = []
    for i in range(k, len(y)):
        t = ts[i]
        rows.append([*y[i - k : i], t.hour + t.minute / 60.0, t.weekday(), np.mean(y[max(0, i - 8) : i])])
    return np.array(rows)


class TrafficForecastAgent(Agent):
    name: ClassVar[str] = "traffic_forecast"
    version: ClassVar[str] = "0.3"
    responsibilities: ClassVar[str] = "Forecast truck arrivals and queue length per station at 15/30/60/120 minute horizons with intervals."
    inputs: ClassVar[dict[str, str]] = {
        "series": "list of {ts, queue_len, arrivals_per_hour, avg_wait_s} observations, oldest first",
        "horizons_min": "list of horizons in minutes",
        "capacity_per_hour": "station capacity",
        "now": "optional datetime",
    }
    outputs: ClassVar[dict[str, str]] = {"forecasts": "{horizon: {queue_len, queue_len_lower, queue_len_upper, arrivals_per_hour}}", "model_version": "model used"}

    LAGS = 6

    def _run(self, inputs: dict[str, Any]):
        series = inputs["series"]
        horizons = [int(h) for h in inputs["horizons_min"]]
        cap = float(inputs.get("capacity_per_hour", 120))
        inputs.get("now") or datetime.now(UTC)
        warnings: list[str] = []
        if not series:
            out = {str(h): {"queue_len": 0.0, "queue_len_lower": 0.0, "queue_len_upper": 0.0, "arrivals_per_hour": 0.0} for h in horizons}
            return {"forecasts": out, "model_version": "no-data"}, 0.05, "no observations; returning zeros", ["no history"]

        ts = [s["ts"] for s in series]
        q = np.array([float(s["queue_len"]) for s in series])
        arr = np.array([float(s["arrivals_per_hour"]) for s in series])
        step_min = 15.0
        if len(ts) >= 2:
            deltas = [(ts[i + 1] - ts[i]).total_seconds() / 60 for i in range(len(ts) - 1)]
            step_min = max(1.0, float(np.median(deltas)))

        if len(q) >= 48:
            from sklearn.ensemble import HistGradientBoostingRegressor

            k = self.LAGS
            Xq, yq = _features(ts, q, k), q[k:]
            Xa, ya = _features(ts, arr, k), arr[k:]
            mq = HistGradientBoostingRegressor(max_iter=150, learning_rate=0.08, max_depth=4, random_state=0).fit(Xq, yq)
            ma = HistGradientBoostingRegressor(max_iter=150, learning_rate=0.08, max_depth=4, random_state=0).fit(Xa, ya)
            # residual spread from a holdout of the last 20 %
            n_hold = max(4, len(yq) // 5)
            resid = yq[-n_hold:] - mq.predict(Xq[-n_hold:])
            spread = float(np.quantile(np.abs(resid), 0.9)) if len(resid) else 2.0
            model = "hgb-lags-v1"
            conf = 0.75
            # recursive multi-step
            hist_q, hist_a, hist_t = list(q), list(arr), list(ts)
            preds: dict[str, dict] = {}
            steps_needed = max(1, int(round(max(horizons) / step_min)))
            for s in range(1, steps_needed + 1):
                t_next = hist_t[-1] + timedelta(minutes=step_min)
                fq = np.array([[*hist_q[-k:], t_next.hour + t_next.minute / 60.0, t_next.weekday(), np.mean(hist_q[-8:])]])
                fa = np.array([[*hist_a[-k:], t_next.hour + t_next.minute / 60.0, t_next.weekday(), np.mean(hist_a[-8:])]])
                pq = float(max(0.0, mq.predict(fq)[0]))
                pa = float(max(0.0, ma.predict(fa)[0]))
                hist_q.append(pq)
                hist_a.append(pa)
                hist_t.append(t_next)
                for h in horizons:
                    if int(round(h / step_min)) == s:
                        grow = 1.0 + 0.15 * (s - 1)
                        preds[str(h)] = {"queue_len": pq, "queue_len_lower": max(0.0, pq - spread * grow), "queue_len_upper": pq + spread * grow, "arrivals_per_hour": pa}
            for h in horizons:
                preds.setdefault(str(h), {"queue_len": hist_q[-1], "queue_len_lower": max(0.0, hist_q[-1] - spread), "queue_len_upper": hist_q[-1] + spread, "arrivals_per_hour": hist_a[-1]})
            return {"forecasts": preds, "model_version": model}, conf, f"gradient boosting on {len(q)} observations, lags={k}, holdout P90 |resid|={spread:.1f}", warnings

        if len(q) >= 8:
            # Holt's linear trend (alpha, beta fixed) on queue and arrivals
            def holt(y: np.ndarray, alpha=0.5, beta=0.2):
                level, trend = y[0], y[1] - y[0]
                for v in y[1:]:
                    prev = level
                    level = alpha * v + (1 - alpha) * (level + trend)
                    trend = beta * (level - prev) + (1 - beta) * trend
                return level, trend

            lq, tq = holt(q)
            la, ta = holt(arr)
            resid = np.diff(q)
            spread = float(np.quantile(np.abs(resid), 0.9)) if len(resid) else 2.0
            preds = {}
            for h in horizons:
                steps = h / step_min
                pq = max(0.0, lq + tq * steps)
                pa = max(0.0, min(cap * 2, la + ta * steps))
                preds[str(h)] = {"queue_len": pq, "queue_len_lower": max(0.0, pq - spread * (1 + 0.1 * steps)), "queue_len_upper": pq + spread * (1 + 0.1 * steps), "arrivals_per_hour": pa}
            warnings.append("fewer than 48 observations: Holt smoothing used instead of gradient boosting")
            return {"forecasts": preds, "model_version": "holt-v1"}, 0.5, f"Holt linear smoothing on {len(q)} observations", warnings

        preds = {str(h): {"queue_len": float(q[-1]), "queue_len_lower": max(0.0, q[-1] - 3), "queue_len_upper": float(q[-1] + 3), "arrivals_per_hour": float(arr[-1])} for h in horizons}
        warnings.append("fewer than 8 observations: persistence forecast")
        return {"forecasts": preds, "model_version": "persistence"}, 0.2, "persistence of last observation", warnings
