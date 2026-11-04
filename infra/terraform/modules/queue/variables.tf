variable "name_prefix" {
  description = "Prefix for resource names, e.g. kifaru-prod."
  type        = string
}

variable "visibility_timeout_seconds" {
  description = "How long a message is hidden after a consumer receives it. Must exceed the worst-case job duration."
  type        = number
  default     = 120
}

variable "message_retention_seconds" {
  description = "Retention of unconsumed messages on the main queue (default 4 days)."
  type        = number
  default     = 345600
}

variable "dlq_retention_seconds" {
  description = "Retention on the dead-letter queue (default 14 days, the SQS maximum)."
  type        = number
  default     = 1209600
}

variable "max_receive_count" {
  description = "Deliveries before a message is moved to the DLQ."
  type        = number
  default     = 5
}

variable "kms_key_arn" {
  description = "Customer-managed KMS key for queue encryption. null = SQS-managed SSE."
  type        = string
  default     = null
}

variable "tags" {
  description = "Tags applied to every resource."
  type        = map(string)
  default     = {}
}
