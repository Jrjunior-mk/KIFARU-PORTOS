variable "name_prefix" {
  description = "Prefix for resource names, e.g. kifaru-prod."
  type        = string
}

variable "github_org" {
  description = "GitHub organisation or user that owns the repository."
  type        = string
}

variable "github_repo" {
  description = "Repository name (without the org)."
  type        = string
}

variable "allowed_subjects" {
  description = <<-EOT
    OIDC `sub` claims allowed to assume the deploy role, relative to repo:<org>/<repo>:. Examples:
      ["ref:refs/heads/main", "ref:refs/tags/v*", "environment:staging", "environment:prod"]
    Keep this tight: anyone able to satisfy a subject can deploy.
  EOT
  type        = list(string)
}

variable "create_oidc_provider" {
  description = "Create the GitHub OIDC provider. One per AWS account: set true in exactly one environment root per account (or in bootstrap) and false elsewhere."
  type        = bool
  default     = true
}

variable "ecr_repository_arns" {
  description = "ECR repositories the deploy role may push to."
  type        = list(string)
}

variable "ecs_cluster_arn" {
  description = "ECS cluster ARN the deploy role may run migrate tasks in."
  type        = string
}

variable "ecs_task_role_arns" {
  description = "Task/execution role ARNs the deploy role may pass to ECS."
  type        = list(string)
}

variable "web_bucket_arn" {
  description = "Web bucket the deploy role may sync the SPA build to."
  type        = string
}

variable "cloudfront_distribution_arns" {
  description = "CloudFront distributions the deploy role may invalidate."
  type        = list(string)
}

variable "state_bucket_arn" {
  description = "Terraform state bucket ARN (for terraform plan/apply in CI)."
  type        = string
}

variable "state_lock_table_arn" {
  description = "Terraform lock table ARN."
  type        = string
}

variable "create_terraform_role" {
  description = "Also create a broader `terraform-apply` role for running terraform apply from CI. Its policy is intentionally wide (infrastructure management) and should be reviewed by the owner."
  type        = bool
  default     = true
}

variable "max_session_duration" {
  description = "Maximum session duration for the roles (seconds)."
  type        = number
  default     = 3600
}

variable "tags" {
  description = "Tags applied to every resource."
  type        = map(string)
  default     = {}
}
