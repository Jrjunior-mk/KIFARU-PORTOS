variable "name_prefix" {
  description = "Prefix for resource names, e.g. kifaru-prod."
  type        = string
}

variable "env" {
  description = "Environment name passed to the application as KIFARU_ENV (dev | staging | prod)."
  type        = string

  validation {
    condition     = contains(["dev", "staging", "prod"], var.env)
    error_message = "env must be dev, staging or prod."
  }
}

variable "vpc_id" {
  description = "VPC ID."
  type        = string
}

variable "public_subnet_ids" {
  description = "Public subnets for the ALB."
  type        = list(string)
}

variable "private_subnet_ids" {
  description = "Private subnets for the Fargate tasks."
  type        = list(string)
}

variable "route53_zone_id" {
  description = "Hosted zone that holds the API origin record and ACM validation records."
  type        = string
}

variable "api_origin_domain" {
  description = "DNS name of the ALB origin used by CloudFront, e.g. api-origin.kifaru.example. Not the public API hostname."
  type        = string
}

variable "restrict_alb_to_cloudfront" {
  description = "Only allow the CloudFront origin-facing prefix list to reach the ALB (true in staging/prod)."
  type        = bool
  default     = true
}

variable "image_tag" {
  description = "Image tag deployed for every service (git SHA or release tag). Set by the deploy workflow via -var."
  type        = string
  default     = "latest"
}

variable "cpu_architecture" {
  description = "Fargate CPU architecture (X86_64 or ARM64). Must match how the images were built."
  type        = string
  default     = "X86_64"

  validation {
    condition     = contains(["X86_64", "ARM64"], var.cpu_architecture)
    error_message = "cpu_architecture must be X86_64 or ARM64."
  }
}

variable "use_fargate_spot" {
  description = "Run services on FARGATE_SPOT (dev only; tasks may be interrupted)."
  type        = bool
  default     = false
}

variable "services" {
  description = <<-EOT
    Long-running services. All run the api image; `command` selects the entrypoint.
    attach_alb services receive traffic from the HTTPS listener for the given path patterns (lower priority = evaluated first).
  EOT
  type = map(object({
    cpu               = number
    memory            = number
    desired_count     = number
    min_count         = number
    max_count         = number
    command           = list(string)
    attach_alb        = bool
    path_patterns     = optional(list(string), [])
    priority          = optional(number, 100)
    container_port    = optional(number, 8000)
    health_check_path = optional(string, "/health")
    cpu_target        = optional(number, 60)
  }))
}

variable "app_environment" {
  description = "Plain (non-secret) KIFARU_* environment variables for all services."
  type        = map(string)
  default     = {}
}

variable "app_secrets" {
  description = "Secret environment variables: env var name => Secrets Manager ARN (optionally with :json-key:: suffix)."
  type        = map(string)
  default     = {}
}

variable "secret_arns" {
  description = "All Secrets Manager ARNs the execution role may read (the base ARNs behind app_secrets and the database JSON secret)."
  type        = list(string)
}

variable "secrets_kms_key_arn" {
  description = "KMS key protecting the secrets (execution role needs kms:Decrypt)."
  type        = string
}

variable "objects_bucket_arn" {
  description = "Objects bucket ARN (task role gets read/write)."
  type        = string
}

variable "backups_bucket_arn" {
  description = "Backups bucket ARN (pg_dump task writes here)."
  type        = string
}

variable "backups_bucket_name" {
  description = "Backups bucket name."
  type        = string
}

variable "s3_kms_key_arn" {
  description = "KMS key encrypting objects/backups buckets."
  type        = string
}

variable "queue_arns" {
  description = "SQS queue ARNs the tasks may send/receive/delete on."
  type        = list(string)
}

variable "access_logs_bucket" {
  description = "Bucket for ALB access logs (prefix alb/)."
  type        = string
}

variable "database_secret_arn" {
  description = "ARN of the JSON database credentials secret (host/port/dbname/username/password) used by the pg_dump task."
  type        = string
}

variable "enable_pg_dump" {
  description = "Create the scheduled pg_dump task (EventBridge -> ECS RunTask)."
  type        = bool
  default     = true
}

variable "pg_dump_schedule" {
  description = "EventBridge schedule expression for pg_dump (UTC). Default 00:30 UTC daily = 03:30 EAT."
  type        = string
  default     = "cron(30 0 * * ? *)"
}

variable "create_seed_task" {
  description = "Create the demo-seed task definition (dev/staging only; never in prod)."
  type        = bool
  default     = false
}

variable "log_retention_days" {
  description = "CloudWatch log retention for service logs."
  type        = number
  default     = 30
}

variable "ecr_keep_images" {
  description = "Number of tagged images kept per ECR repository."
  type        = number
  default     = 30
}

variable "tags" {
  description = "Tags applied to every resource."
  type        = map(string)
  default     = {}
}
