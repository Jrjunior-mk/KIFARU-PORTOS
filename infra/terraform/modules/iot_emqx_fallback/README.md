# iot_emqx_fallback

Self-hosted EMQX 5 broker on ECS Fargate behind a Network Load Balancer. Deployed **only** when AWS IoT Core cannot be
used in `af-south-1` (service unavailable in the region at deployment time, or not approved by the owner). Select it in
the environment root with `iot_mode = "emqx"`; the default `iot_mode = "iot_core"` deploys `modules/iot`.

## What changes for the application

| Aspect | IoT Core (`modules/iot`) | EMQX fallback (this module) |
|---|---|---|
| Device auth | X.509 certificate per Thing, IAM-style IoT policy scoped by `${iot:Connection.Thing.ThingName}` | EMQX built-in auth: per-device username/password **or** X.509 with `verify_peer` on the SSL listener |
| Topic ACL | IoT policy | EMQX authorization rules (file or built-in DB), one rule per device: publish `kifaru/stations/<id>/events`, subscribe `kifaru/stations/<id>/commands` |
| Delivery to backend | Topic rule -> SQS `events` queue, `ingest` polls SQS | `ingest` subscribes directly over MQTT (`KIFARU_MQTT_HOST` = NLB DNS, `KIFARU_MQTT_PORT` = 8883) |
| Durability | SQS (4-day retention, DLQ) | None at the broker; relies on gateway SQLite outbox + QoS 1 redelivery |

## Owner actions before enabling

1. Issue an ACM certificate for `mqtt.<domain>` in `af-south-1` and pass its ARN as `certificate_arn`.
2. Decide the auth mode. For mTLS: bake the station CA into a custom EMQX image or mount it via an EFS volume, set
   `EMQX_LISTENERS__SSL__DEFAULT__SSL_OPTIONS__VERIFY=verify_peer` and switch the NLB listener to TCP passthrough.
3. Restrict `dashboard_cidrs` to the office/VPN range and rotate the dashboard admin password on first login.
4. Create one EMQX user + ACL per gateway (`gw-<station>-l<lane>`), mirroring the IoT Core policy.

## Not included (intentionally)

* EMQX clustering/HA (requires DNS-based discovery and a shared data volume).
* Persistent sessions and retained-message storage.
* Rule engine -> SQS bridge (EMQX can bridge to SQS via its HTTP/Kafka bridges, but the ingest service consuming MQTT
  directly is simpler for a fallback).
