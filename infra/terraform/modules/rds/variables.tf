variable "name_prefix" {
  description = "Prefix for resource names, e.g. kifaru-prod."
  type        = string
}

variable "secret_path_prefix" {
  description = "Secrets Manager name prefix, e.g. kifaru/prod."
  type        = string
}

variable "vpc_id" {
  description = "VPC in which to place the instance."
  type        = string
}

variable "subnet_ids" {
  description = "Private subnet IDs for the DB subnet group (at least two AZs for Multi-AZ)."
  type        = list(string)
}

variable "allowed_security_group_ids" {
  description = "Security groups allowed to connect on 5432 (ECS tasks)."
  type        = list(string)
  default     = []
}

variable "engine_version" {
  description = "PostgreSQL major.minor version (16.x). A bare major lets RDS pick the latest minor."
  type        = string
  default     = "16"
}

variable "instance_class" {
  description = "RDS instance class (dev: db.t4g.micro, staging: db.t4g.small, prod: db.t4g.medium or larger)."
  type        = string
  default     = "db.t4g.micro"
}

variable "allocated_storage" {
  description = "Initial storage (GiB, gp3)."
  type        = number
  default     = 20
}

variable "max_allocated_storage" {
  description = "Storage autoscaling ceiling (GiB). 0 disables autoscaling."
  type        = number
  default     = 200
}

variable "multi_az" {
  description = "Multi-AZ standby (required in prod)."
  type        = bool
  default     = false
}

variable "db_name" {
  description = "Initial database name."
  type        = string
  default     = "kifaru"
}

variable "master_username" {
  description = "Master user name."
  type        = string
  default     = "kifaru_admin"
}

variable "backup_retention_period" {
  description = "Automated backup retention in days (PITR window). 35 is the RDS maximum."
  type        = number
  default     = 35
}

variable "backup_window" {
  description = "Daily backup window (UTC). 00:00-01:00 UTC = 03:00-04:00 EAT, outside weighbridge peak."
  type        = string
  default     = "00:00-01:00"
}

variable "maintenance_window" {
  description = "Weekly maintenance window (UTC)."
  type        = string
  default     = "sun:01:30-sun:02:30"
}

variable "deletion_protection" {
  description = "Prevent accidental deletion (true in staging/prod)."
  type        = bool
  default     = true
}

variable "skip_final_snapshot" {
  description = "Skip the final snapshot on destroy (dev only)."
  type        = bool
  default     = false
}

variable "performance_insights_enabled" {
  description = "Enable Performance Insights (free tier: 7 days)."
  type        = bool
  default     = true
}

variable "enhanced_monitoring_interval" {
  description = "Enhanced Monitoring granularity in seconds (0 disables)."
  type        = number
  default     = 60
}

variable "enable_cross_region_backup_replication" {
  description = "Replicate automated backups (snapshots + transaction logs) to the DR region. Required for the RPO 15 min DR target in prod."
  type        = bool
  default     = false
}

variable "dr_backup_retention_period" {
  description = "Retention of replicated automated backups in the DR region (days)."
  type        = number
  default     = 14
}

variable "rotation_lambda_arn" {
  description = "ARN of a Secrets Manager rotation Lambda (e.g. the SecretsManagerRDSPostgreSQLRotationSingleUser SAR app deployed by the owner). null = rotation not configured."
  type        = string
  default     = null
}

variable "rotation_days" {
  description = "Rotation interval in days when rotation_lambda_arn is set."
  type        = number
  default     = 30
}

variable "secrets_kms_key_arn" {
  description = "KMS key used to encrypt the credential secrets (from the secrets module)."
  type        = string
}

variable "recovery_window_in_days" {
  description = "Secrets Manager recovery window for the DB secrets."
  type        = number
  default     = 30
}

variable "tags" {
  description = "Tags applied to every resource."
  type        = map(string)
  default     = {}
}
