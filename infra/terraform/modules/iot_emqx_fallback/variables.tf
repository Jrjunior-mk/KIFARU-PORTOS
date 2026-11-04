variable "name_prefix" {
  description = "Prefix for resource names, e.g. kifaru-prod."
  type        = string
}

variable "vpc_id" {
  description = "VPC ID."
  type        = string
}

variable "public_subnet_ids" {
  description = "Public subnets for the internet-facing NLB (station gateways connect over LTE)."
  type        = list(string)
}

variable "private_subnet_ids" {
  description = "Private subnets for the EMQX tasks."
  type        = list(string)
}

variable "cluster_arn" {
  description = "ECS cluster ARN to run EMQX in."
  type        = string
}

variable "execution_role_arn" {
  description = "ECS task execution role (ECR pull, logs, secrets)."
  type        = string
}

variable "emqx_image" {
  description = "EMQX container image."
  type        = string
  default     = "public.ecr.aws/emqx/emqx:5.8.3"
}

variable "cpu" {
  description = "Fargate CPU units."
  type        = number
  default     = 512
}

variable "memory" {
  description = "Fargate memory (MiB)."
  type        = number
  default     = 1024
}

variable "certificate_arn" {
  description = "ACM certificate for the NLB TLS listener on 8883 (server-side TLS). Client certificates are verified by EMQX itself when `mtls` is enabled in its config; see README."
  type        = string
}

variable "allowed_cidrs" {
  description = "CIDRs allowed to reach 8883. Station LTE gateways rarely have fixed IPs; default is open and relies on TLS + per-device credentials."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "dashboard_cidrs" {
  description = "CIDRs allowed to reach the EMQX dashboard (18083). Keep to the office/VPN range."
  type        = list(string)
  default     = []
}

variable "log_retention_days" {
  description = "CloudWatch log retention."
  type        = number
  default     = 30
}

variable "tags" {
  description = "Tags applied to every resource."
  type        = map(string)
  default     = {}
}
