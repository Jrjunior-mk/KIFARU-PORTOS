# ---------------------------------------------------------------------------------------------------------------------
# Environment root variables. This file is IDENTICAL across envs/dev, envs/staging and envs/prod; environment differences
# live in terraform.tfvars (see terraform.tfvars.example). Keep it that way when editing.
# ---------------------------------------------------------------------------------------------------------------------

# --- Identity ------------------------------------------------------------------------------------------------------------

variable "env" {
  description = "Environment name: dev | staging | prod. Drives naming (kifaru-<env>), KIFARU_ENV and safety switches."
  type        = string

  validation {
    condition     = contains(["dev", "staging", "prod"], var.env)
    error_message = "env must be dev, staging or prod."
  }
}

variable "aws_region" {
  description = "Primary region."
  type        = string
  default     = "af-south-1"
}

variable "dr_region" {
  description = "Disaster-recovery region for S3 replicas and RDS backup replication."
  type        = string
  default     = "eu-west-1"
}

variable "extra_tags" {
  description = "Additional tags merged into every resource."
  type        = map(string)
  default     = {}
}

# --- Owner-provided inputs (see docs/06-operations/deployment-guide.md section 2) ----------------------------------------

variable "route53_zone_id" {
  description = "Hosted zone ID of the registered domain (owner-provided)."
  type        = string
}

variable "web_domain" {
  description = "Public SPA hostname, e.g. app.dev.kifaru.example."
  type        = string
}

variable "api_domain" {
  description = "Public API/WebSocket hostname, e.g. api.dev.kifaru.example."
  type        = string
}

variable "api_origin_domain" {
  description = "ALB origin hostname used only by CloudFront, e.g. api-origin.dev.kifaru.example."
  type        = string
}

variable "alarm_email" {
  description = "E-mail for CloudWatch alarm notifications (owner-provided; empty disables the subscription)."
  type        = string
  default     = ""
}

variable "github_org" {
  description = "GitHub organisation/user owning the repository (OIDC trust)."
  type        = string
}

variable "github_repo" {
  description = "GitHub repository name (OIDC trust)."
  type        = string
}

variable "github_allowed_subjects" {
  description = "OIDC subjects allowed to deploy this environment, e.g. [\"environment:dev\", \"ref:refs/heads/main\"]."
  type        = list(string)
}

variable "create_oidc_provider" {
  description = "Create the account-level GitHub OIDC provider from this root (true in exactly one root per AWS account)."
  type        = bool
  default     = true
}

variable "state_bucket_arn" {
  description = "ARN of the Terraform state bucket created by bootstrap/."
  type        = string
}

variable "state_lock_table_arn" {
  description = "ARN of the DynamoDB lock table created by bootstrap/."
  type        = string
}

# --- Images ------------------------------------------------------------------------------------------------------------

variable "image_tag" {
  description = "Image tag to deploy (git SHA or release tag). The deploy workflow passes -var image_tag=..."
  type        = string
  default     = "latest"
}

variable "cpu_architecture" {
  description = "Fargate CPU architecture, must match the image build (X86_64 | ARM64)."
  type        = string
  default     = "X86_64"
}

# --- Network -----------------------------------------------------------------------------------------------------------

variable "vpc_cidr" {
  description = "VPC CIDR."
  type        = string
  default     = "10.40.0.0/16"
}

variable "single_nat_gateway" {
  description = "One NAT gateway for all AZs (cheaper) instead of one per AZ."
  type        = bool
  default     = true
}

variable "enable_interface_endpoints" {
  description = "Create interface VPC endpoints (ECR, Secrets Manager, Logs, SQS, KMS)."
  type        = bool
  default     = true
}

# --- Compute -----------------------------------------------------------------------------------------------------------

variable "services" {
  description = "ECS services (api, realtime, worker, ingest). See modules/ecs for field meanings."
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
  default = {
    api = {
      cpu           = 512
      memory        = 1024
      desired_count = 1
      min_count     = 1
      max_count     = 2
      command       = ["uvicorn", "kifaru.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--proxy-headers", "--forwarded-allow-ips", "*"]
      attach_alb    = true
      priority      = 100
    }
    realtime = {
      cpu           = 256
      memory        = 512
      desired_count = 1
      min_count     = 1
      max_count     = 2
      command       = ["uvicorn", "kifaru.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers", "--forwarded-allow-ips", "*"]
      attach_alb    = true
      path_patterns = ["/ws/*"]
      priority      = 10
    }
    worker = {
      cpu           = 256
      memory        = 512
      desired_count = 1
      min_count     = 1
      max_count     = 2
      command       = ["python", "-m", "kifaru.worker"]
      attach_alb    = false
    }
    ingest = {
      cpu           = 256
      memory        = 512
      desired_count = 1
      min_count     = 1
      max_count     = 2
      command       = ["python", "-m", "kifaru.ingest"]
      attach_alb    = false
    }
  }
}

variable "use_fargate_spot" {
  description = "Run on FARGATE_SPOT (dev only)."
  type        = bool
  default     = false
}

variable "restrict_alb_to_cloudfront" {
  description = "Allow only CloudFront origin-facing IPs to reach the ALB."
  type        = bool
  default     = true
}

variable "create_seed_task" {
  description = "Create the demo-seed ECS task definition. Ignored (forced off) when env = prod."
  type        = bool
  default     = false
}

variable "log_level" {
  description = "KIFARU_LOG_LEVEL."
  type        = string
  default     = "INFO"
}

variable "signing_key_id" {
  description = "KIFARU_SIGNING_KEY_ID: identifier embedded in signed tickets so verifiers can select the key."
  type        = string
  default     = "platform-key-v1"
}

variable "log_retention_days" {
  description = "CloudWatch log retention for application logs."
  type        = number
  default     = 30
}

# --- Database ----------------------------------------------------------------------------------------------------------

variable "rds_instance_class" {
  description = "RDS instance class."
  type        = string
  default     = "db.t4g.micro"
}

variable "rds_allocated_storage" {
  description = "Initial RDS storage (GiB)."
  type        = number
  default     = 20
}

variable "rds_max_allocated_storage" {
  description = "RDS storage autoscaling ceiling (GiB)."
  type        = number
  default     = 200
}

variable "rds_multi_az" {
  description = "Multi-AZ RDS."
  type        = bool
  default     = false
}

variable "rds_deletion_protection" {
  description = "RDS deletion protection."
  type        = bool
  default     = true
}

variable "rds_skip_final_snapshot" {
  description = "Skip final snapshot on destroy (dev only)."
  type        = bool
  default     = false
}

variable "rds_cross_region_backup_replication" {
  description = "Replicate RDS automated backups to the DR region."
  type        = bool
  default     = false
}

variable "rds_rotation_lambda_arn" {
  description = "Secrets Manager rotation Lambda ARN for the DB credentials (null = no rotation configured)."
  type        = string
  default     = null
}

variable "rds_max_connections_alarm" {
  description = "DatabaseConnections alarm threshold."
  type        = number
  default     = 60
}

# --- Redis -------------------------------------------------------------------------------------------------------------

variable "redis_node_type" {
  description = "ElastiCache node type."
  type        = string
  default     = "cache.t4g.micro"
}

variable "redis_num_cache_clusters" {
  description = "Redis nodes (1 = single, 2+ = HA)."
  type        = number
  default     = 1
}

variable "redis_snapshot_retention_limit" {
  description = "Redis snapshot retention (days)."
  type        = number
  default     = 7
}

# --- Storage -----------------------------------------------------------------------------------------------------------

variable "s3_enable_replication" {
  description = "Cross-region replication of objects/backups buckets."
  type        = bool
  default     = true
}

variable "s3_force_destroy" {
  description = "Allow destroying non-empty buckets (dev only)."
  type        = bool
  default     = false
}

# --- IoT ---------------------------------------------------------------------------------------------------------------

variable "iot_mode" {
  description = "iot_core (AWS IoT Core, default) | emqx (self-hosted fallback) | none (no broker; e.g. dev using the simulator only)."
  type        = string
  default     = "iot_core"

  validation {
    condition     = contains(["iot_core", "emqx", "none"], var.iot_mode)
    error_message = "iot_mode must be iot_core, emqx or none."
  }
}

variable "emqx_certificate_arn" {
  description = "Regional ACM certificate ARN for the EMQX NLB listener (required when iot_mode = emqx)."
  type        = string
  default     = null
}

variable "enable_iot_logging" {
  description = "Enable account-level IoT logging from this root (one root per account)."
  type        = bool
  default     = false
}

# --- Edge --------------------------------------------------------------------------------------------------------------

variable "cloudfront_price_class" {
  description = "CloudFront price class (PriceClass_All reaches the African PoPs)."
  type        = string
  default     = "PriceClass_All"
}

variable "waf_rate_limit" {
  description = "WAF global rate limit per IP per 5 minutes."
  type        = number
  default     = 2000
}

variable "waf_rate_limit_auth" {
  description = "WAF rate limit per IP per 5 minutes on /api/v1/auth/*."
  type        = number
  default     = 100
}

# --- Secrets -----------------------------------------------------------------------------------------------------------

variable "secrets_recovery_window_in_days" {
  description = "Secrets Manager recovery window (0 allows immediate deletion; dev only)."
  type        = number
  default     = 30
}

# --- Backups -----------------------------------------------------------------------------------------------------------

variable "enable_pg_dump" {
  description = "Create the daily pg_dump scheduled task."
  type        = bool
  default     = true
}

variable "pg_dump_schedule" {
  description = "EventBridge cron for pg_dump (UTC)."
  type        = string
  default     = "cron(30 0 * * ? *)"
}
