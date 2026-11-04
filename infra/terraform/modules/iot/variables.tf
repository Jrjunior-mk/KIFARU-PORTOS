variable "name_prefix" {
  description = "Prefix for resource names, e.g. kifaru-prod."
  type        = string
}

variable "events_queue_arn" {
  description = "ARN of the SQS queue that receives station events."
  type        = string
}

variable "events_queue_url" {
  description = "URL of the SQS queue that receives station events."
  type        = string
}

variable "topic_prefix" {
  description = "MQTT topic prefix. Gateways publish to <prefix>/<thing name>/events and subscribe to <prefix>/<thing name>/commands."
  type        = string
  default     = "kifaru/stations"
}

variable "log_retention_days" {
  description = "Retention of IoT rule error logs."
  type        = number
  default     = 30
}

variable "enable_iot_logging" {
  description = "Enable account-level AWS IoT logging (one per account/region; set true in exactly one environment per account)."
  type        = bool
  default     = false
}

variable "tags" {
  description = "Tags applied to every resource."
  type        = map(string)
  default     = {}
}
