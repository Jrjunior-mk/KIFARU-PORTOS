variable "aws_region" {
  description = "Region for the state bucket and lock table (same as the workloads: af-south-1)."
  type        = string
  default     = "af-south-1"
}

variable "state_bucket_name" {
  description = "Globally unique state bucket name. Empty = kifaru-terraform-state-<account id>."
  type        = string
  default     = ""
}

variable "lock_table_name" {
  description = "DynamoDB lock table name."
  type        = string
  default     = "kifaru-terraform-locks"
}
