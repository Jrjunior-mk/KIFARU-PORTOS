variable "name_prefix" {
  description = "Prefix for resource names, e.g. kifaru-prod."
  type        = string
}

variable "alarm_email" {
  description = "E-mail address subscribed to the alarm SNS topic (the recipient must confirm the subscription). Empty = no subscription."
  type        = string
  default     = ""
}

variable "alb_arn_suffix" {
  description = "ALB ARN suffix (app/<name>/<id>)."
  type        = string
}

variable "target_group_arn_suffixes" {
  description = "Map service key => target group ARN suffix."
  type        = map(string)
}

variable "ecs_cluster_name" {
  description = "ECS cluster name."
  type        = string
}

variable "ecs_service_names" {
  description = "Map service key => ECS service name."
  type        = map(string)
}

variable "rds_instance_identifier" {
  description = "RDS instance identifier."
  type        = string
}

variable "rds_max_connections" {
  description = "Connection alarm threshold (roughly 80 % of the instance's max_connections; db.t4g.micro ~ 80, small ~ 170, medium ~ 400)."
  type        = number
  default     = 60
}

variable "rds_free_storage_threshold_bytes" {
  description = "Alarm when RDS free storage drops below this many bytes (default 2 GiB)."
  type        = number
  default     = 2147483648
}

variable "redis_replication_group_id" {
  description = "ElastiCache replication group ID."
  type        = string
}

variable "dlq_names" {
  description = "Map queue key => DLQ name."
  type        = map(string)
}

variable "events_queue_name" {
  description = "Name of the station-events queue (age-of-oldest-message alarm)."
  type        = string
}

variable "alb_5xx_threshold" {
  description = "ALB/target 5xx count per 5 minutes that triggers the alarm."
  type        = number
  default     = 20
}

variable "api_latency_p99_threshold_seconds" {
  description = "p99 target response time threshold (seconds)."
  type        = number
  default     = 2
}

variable "tags" {
  description = "Tags applied to every resource."
  type        = map(string)
  default     = {}
}
