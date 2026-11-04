"""Entry point used by the ECS `worker` service and Docker Compose: `python -m kifaru.worker`.

Runs the periodic jobs worker (queue forecasts, release predictions, incident recommendations, security anomaly scan).
"""
from __future__ import annotations

from .workers.jobs import main

if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
