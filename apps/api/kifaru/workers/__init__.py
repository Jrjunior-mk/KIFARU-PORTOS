"""Background workers (run as separate processes next to the API):

* ``python -m kifaru.workers.mqtt_ingest`` — MQTT subscriber for edge lane events and sensor health (EMQX locally,
  AWS IoT Core with mTLS in the cloud).
* ``python -m kifaru.workers.sqs_ingest`` — same handler fed from an SQS queue (IoT Core rule -> SQS path).
* ``python -m kifaru.workers.jobs`` — periodic forecasts, release predictions and incident recommendations.
"""
