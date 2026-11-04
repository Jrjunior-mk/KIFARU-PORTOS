output "mqtt_endpoint" {
  description = "NLB DNS name; gateways and the ingest service connect on 8883 (TLS)."
  value       = aws_lb.emqx.dns_name
}

output "security_group_id" {
  description = "Security group of the EMQX tasks."
  value       = aws_security_group.emqx.id
}

output "service_name" {
  description = "ECS service name."
  value       = aws_ecs_service.emqx.name
}
