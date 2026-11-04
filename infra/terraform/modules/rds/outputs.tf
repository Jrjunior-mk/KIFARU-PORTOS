output "instance_identifier" {
  description = "RDS instance identifier (for alarms and snapshot commands)."
  value       = aws_db_instance.this.identifier
}

output "instance_arn" {
  description = "RDS instance ARN."
  value       = aws_db_instance.this.arn
}

output "address" {
  description = "Instance endpoint hostname."
  value       = aws_db_instance.this.address
}

output "port" {
  description = "PostgreSQL port."
  value       = local.port
}

output "db_name" {
  description = "Database name."
  value       = var.db_name
}

output "security_group_id" {
  description = "RDS security group."
  value       = aws_security_group.this.id
}

output "kms_key_arn" {
  description = "KMS key encrypting the instance storage and snapshots."
  value       = aws_kms_key.rds.arn
}

output "dr_kms_key_arn" {
  description = "KMS key for replicated backups in the DR region (null when disabled)."
  value       = var.enable_cross_region_backup_replication ? aws_kms_key.rds_dr[0].arn : null
}

output "database_secret_arn" {
  description = "ARN of the JSON credentials secret (<prefix>/database)."
  value       = aws_secretsmanager_secret.database.arn
}

output "database_url_secret_arn" {
  description = "ARN of the SQLAlchemy URL secret (<prefix>/database-url -> KIFARU_DATABASE_URL)."
  value       = aws_secretsmanager_secret.database_url.arn
}
