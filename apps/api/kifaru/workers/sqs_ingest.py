"""SQS ingest worker — the AWS path: IoT Core rule (`SELECT *, topic() AS topic FROM 'kifaru/stations/+/lanes/+/+'`)
-> SQS queue (with a redrive policy to a DLQ) -> this consumer -> the same handlers as the MQTT worker.

boto3 is an optional dependency: the module imports without it and only ``main``/``SqsIngestWorker`` require it.

Message body: either the raw gateway JSON (EdgeIngestIn / EdgeHealthIn) or the IoT-rule envelope
``{"topic": "kifaru/stations/MRK/lanes/1/events", "payload": {...}}`` / a flat object with a ``topic`` key.

Run:  python -m kifaru.workers.sqs_ingest --queue-url https://sqs.af-south-1.amazonaws.com/123456789012/kifaru-ingest
"""
from __future__ import annotations

import argparse
import json
import logging
import signal
import sys
import threading

import structlog

from ..config import get_settings
from ..db import get_sessionmaker
from .mqtt_ingest import TOPIC_EVENTS, HandleResult, dead_letter, dispatch

log = structlog.get_logger("kifaru.workers.sqs_ingest")

try:  # optional
    import boto3  # type: ignore
except ImportError:  # pragma: no cover
    boto3 = None


def topic_and_payload(body: str | bytes | dict) -> tuple[str, dict | str | bytes]:
    """Extract (topic, payload) from an SQS body. Falls back to the events topic when no topic is present."""
    try:
        data = json.loads(body) if not isinstance(body, dict) else body
    except (ValueError, TypeError):
        return TOPIC_EVENTS, body
    if not isinstance(data, dict):
        return TOPIC_EVENTS, body
    topic = str(data.get("topic") or TOPIC_EVENTS)
    if "payload" in data and isinstance(data["payload"], dict):
        return topic, data["payload"]
    if "payload" in data and isinstance(data["payload"], str):
        return topic, data["payload"]
    return topic, data


def handle_sqs_body(db, body: str | bytes | dict, dead_letter_directory=None) -> HandleResult:
    topic, payload = topic_and_payload(body)
    return dispatch(db, topic, payload, dead_letter_directory)


class SqsIngestWorker:
    def __init__(self, queue_url: str, region: str | None = None, wait_s: int = 20, batch: int = 10) -> None:
        if boto3 is None:
            raise SystemExit("boto3 is not installed; install with `pip install boto3` to use the SQS ingest worker.")
        s = get_settings()
        self.queue_url = queue_url
        self.sqs = boto3.client("sqs", region_name=region or s.s3_region)
        self.wait_s, self.batch = wait_s, batch
        self.Session = get_sessionmaker()
        self.stats = {"processed": 0, "duplicate": 0, "dead_letter": 0, "health_updated": 0}
        self._stop = threading.Event()

    def poll_once(self) -> int:
        resp = self.sqs.receive_message(QueueUrl=self.queue_url, MaxNumberOfMessages=self.batch, WaitTimeSeconds=self.wait_s, AttributeNames=["ApproximateReceiveCount"])
        msgs = resp.get("Messages", [])
        for m in msgs:
            with self.Session() as db:
                try:
                    res = handle_sqs_body(db, m.get("Body", ""))
                except Exception as exc:  # noqa: BLE001 - belt and braces; handlers already catch
                    dead_letter(TOPIC_EVENTS, m.get("Body", ""), f"unexpected: {exc}")
                    res = HandleResult("dead_letter", str(exc))
            self.stats[res.status] = self.stats.get(res.status, 0) + 1
            # delete = ack. Dead-lettered messages are also deleted: they are persisted locally and the SQS DLQ is for
            # messages this worker could not even read.
            self.sqs.delete_message(QueueUrl=self.queue_url, ReceiptHandle=m["ReceiptHandle"])
        return len(msgs)

    def run_forever(self) -> None:
        signal.signal(signal.SIGINT, lambda *_: self._stop.set())
        signal.signal(signal.SIGTERM, lambda *_: self._stop.set())
        log.info("sqs_ingest_starting", queue=self.queue_url)
        while not self._stop.is_set():
            try:
                self.poll_once()
            except Exception as exc:  # noqa: BLE001 - network blips must not kill the worker
                log.warning("sqs_poll_failed", error=str(exc))
                self._stop.wait(5.0)
        log.info("sqs_ingest_stopped", **self.stats)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="KIFARU PORTOS SQS ingest worker (AWS IoT Core -> SQS path)")
    p.add_argument("--queue-url", required=True)
    p.add_argument("--region", default=None)
    a = p.parse_args(argv)
    logging.basicConfig(level=get_settings().log_level, stream=sys.stdout)
    SqsIngestWorker(a.queue_url, a.region).run_forever()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
