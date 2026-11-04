output "replication_group_id" {
  description = "Replication group ID (for alarms and snapshot commands)."
  value       = aws_elasticache_replication_group.this.id
}

output "primary_endpoint_address" {
  description = "Primary endpoint hostname."
  value       = aws_elasticache_replication_group.this.primary_endpoint_address
}

output "port" {
  description = "Redis port."
  value       = local.port
}

output "security_group_id" {
  description = "Redis security group."
  value       = aws_security_group.this.id
}

output "redis_url_secret_arn" {
  description = "ARN of the Redis URL secret (-> KIFARU_REDIS_URL)."
  value       = aws_secretsmanager_secret.redis_url.arn
}
