variable "name_prefix" {
  description = "Prefix for resource names, e.g. kifaru-prod."
  type        = string
}

variable "secret_path_prefix" {
  description = "Secrets Manager name prefix, e.g. kifaru/prod. Application secrets are created beneath it."
  type        = string
}

variable "recovery_window_in_days" {
  description = "Days Secrets Manager keeps a deleted secret recoverable (0 = immediate delete, dev only)."
  type        = number
  default     = 30
}

variable "external_adapter_keys" {
  description = "Keys of third-party credentials to reserve in the app-secrets JSON (values are placeholders the owner fills in the console or CLI; never in Terraform)."
  type        = list(string)
  default     = ["KIFARU_AT_USERNAME", "KIFARU_AT_API_KEY", "KIFARU_INT_KENHA_TOKEN", "KIFARU_INT_KRA_TOKEN", "KIFARU_INT_NTSA_TOKEN", "KIFARU_SENTRY_DSN"]
}

variable "signing_key_id" {
  description = "Identifier of the platform Ed25519 signing key, surfaced to the API as KIFARU_SIGNING_KEY_ID."
  type        = string
}

variable "tags" {
  description = "Tags applied to every resource."
  type        = map(string)
  default     = {}
}
