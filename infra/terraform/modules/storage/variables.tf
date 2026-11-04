variable "name_prefix" {
  description = "Prefix for resource names, e.g. kifaru-prod. Bucket names are <name_prefix>-<purpose>-<account id>."
  type        = string
}

variable "enable_replication" {
  description = "Replicate the objects and backups buckets to the DR region (eu-west-1). Disable in dev to save cost."
  type        = bool
  default     = true
}

variable "tickets_retention_days" {
  description = "Default Object Lock (COMPLIANCE) retention for objects under tickets/. Weighing tickets are legal evidence: 7 years."
  type        = number
  default     = 2555
}

variable "evidence_expiration_days" {
  description = "Days after which evidence images (evidence/) expire. Raw WIM signal snapshots (raw-signals/) expire after raw_signal_expiration_days."
  type        = number
  default     = 365
}

variable "raw_signal_expiration_days" {
  description = "Days after which raw-signals/ objects expire (only decimated statistics are kept in PostgreSQL)."
  type        = number
  default     = 90
}

variable "backup_expiration_days" {
  description = "Days after which pg_dump backups expire (default ~13 months so the yearly dump survives a year-end audit)."
  type        = number
  default     = 400
}

variable "noncurrent_version_expiration_days" {
  description = "Days before non-current (overwritten) object versions are removed outside tickets/."
  type        = number
  default     = 90
}

variable "access_log_expiration_days" {
  description = "Retention of ALB access logs."
  type        = number
  default     = 90
}

variable "force_destroy" {
  description = "Allow Terraform to delete non-empty buckets (dev only; never in prod)."
  type        = bool
  default     = false
}

variable "tags" {
  description = "Tags applied to every resource."
  type        = map(string)
  default     = {}
}
