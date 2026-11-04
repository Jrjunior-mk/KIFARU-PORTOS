output "mqtt_endpoint" {
  description = "IoT Core data endpoint (ATS). Gateways and the ingest service connect here on 8883 with mTLS."
  value       = data.aws_iot_endpoint.data.endpoint_address
}

output "thing_type_name" {
  description = "Thing type to use when registering gateways."
  value       = aws_iot_thing_type.station_gateway.name
}

output "device_policy_name" {
  description = "IoT policy to attach to each gateway certificate."
  value       = aws_iot_policy.device.name
}

output "topic_rule_name" {
  description = "Name of the events -> SQS topic rule."
  value       = aws_iot_topic_rule.station_events.name
}

output "topic_prefix" {
  description = "MQTT topic prefix in use."
  value       = var.topic_prefix
}
