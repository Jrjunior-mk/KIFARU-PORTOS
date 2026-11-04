"""Entry point used by the ECS `ingest` service and Docker Compose: `python -m kifaru.ingest`.

Selects the transport from KIFARU_IOT_MODE:
  emqx     -> MQTT subscriber (local EMQX or any MQTT 5 broker; mTLS when certs are configured)
  iot_core -> SQS consumer fed by the AWS IoT Core topic rule (KIFARU_EVENTS_QUEUE_URL)
  none     -> exit 0 (HTTP ingest only)
"""
from __future__ import annotations

import sys

from .config import get_settings


def main() -> int:
    s = get_settings()
    if s.iot_mode == "emqx":
        from .workers.mqtt_ingest import main as mqtt_main

        return mqtt_main()
    if s.iot_mode == "iot_core":
        from .workers.sqs_ingest import main as sqs_main

        return sqs_main()
    print("KIFARU_IOT_MODE=none: no device transport configured; HTTP /weighing/ingest remains available", file=sys.stderr)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
