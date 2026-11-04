variable "name_prefix" {
  description = "Prefix for resource names, e.g. kifaru-prod."
  type        = string
}

variable "secret_path_prefix" {
  description = "Secrets Manager name prefix, e.g. kifaru/prod."
  type        = string
}

variable "vpc_id" {
  description = "VPC ID."
  type        = string
}

variable "subnet_ids" {
  description = "Private subnet IDs for the cache subnet group."
  type        = list(string)
}

variable "allowed_security_group_ids" {
  description = "Security groups allowed to connect on 6379 (ECS tasks)."
  type        = list(string)
  default     = []
}

variable "node_type" {
  description = "Node type (dev/staging: cache.t4g.micro, prod: cache.t4g.small or larger)."
  type        = string
  default     = "cache.t4g.micro"
}

variable "engine_version" {
  description = "Redis engine version (7.x)."
  type        = string
  default     = "7.1"
}

variable "num_cache_clusters" {
  description = "Number of nodes in the replication group. 1 = single node (dev); 2+ enables automatic failover and Multi-AZ."
  type        = number
  default     = 1
}

variable "snapshot_retention_limit" {
  description = "Days to keep automatic snapshots (0 disables; not supported on cache.t4g.micro/t3.micro in some regions, set 0 for those)."
  type        = number
  default     = 7
}

variable "snapshot_window" {
  description = "Daily snapshot window (UTC)."
  type        = string
  default     = "01:00-02:00"
}

variable "maintenance_window" {
  description = "Weekly maintenance window (UTC)."
  type        = string
  default     = "sun:02:30-sun:03:30"
}

variable "secrets_kms_key_arn" {
  description = "KMS key for the Redis secrets."
  type        = string
}

variable "recovery_window_in_days" {
  description = "Secrets Manager recovery window."
  type        = number
  default     = 30
}

variable "tags" {
  description = "Tags applied to every resource."
  type        = map(string)
  default     = {}
}
