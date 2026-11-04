variable "name_prefix" {
  description = "Prefix for all resource names, e.g. kifaru-prod."
  type        = string
}

variable "vpc_cidr" {
  description = "CIDR block for the VPC (a /16 is recommended; subnets are carved as /20s)."
  type        = string
  default     = "10.40.0.0/16"
}

variable "az_count" {
  description = "Number of Availability Zones to spread public/private subnets across (2 for all environments)."
  type        = number
  default     = 2

  validation {
    condition     = var.az_count >= 1 && var.az_count <= 3
    error_message = "az_count must be between 1 and 3."
  }
}

variable "single_nat_gateway" {
  description = "true = one shared NAT gateway (cheaper, dev/staging); false = one NAT gateway per AZ (prod)."
  type        = bool
  default     = true
}

variable "enable_interface_endpoints" {
  description = "Create interface VPC endpoints (ECR API/DKR, Secrets Manager, CloudWatch Logs, SQS, KMS). Keeps traffic off the NAT gateway; about USD 7/month each, so dev may disable them."
  type        = bool
  default     = true
}

variable "enable_flow_logs" {
  description = "Send VPC flow logs (REJECT traffic) to CloudWatch Logs."
  type        = bool
  default     = true
}

variable "flow_log_retention_days" {
  description = "Retention of VPC flow logs in CloudWatch Logs."
  type        = number
  default     = 30
}

variable "tags" {
  description = "Tags applied to every resource in the module (Project/Env are also injected via provider default_tags)."
  type        = map(string)
  default     = {}
}
