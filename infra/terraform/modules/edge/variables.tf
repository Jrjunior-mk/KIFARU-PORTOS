variable "name_prefix" {
  description = "Prefix for resource names, e.g. kifaru-prod."
  type        = string
}

variable "route53_zone_id" {
  description = "Hosted zone ID for the public domain."
  type        = string
}

variable "web_domain" {
  description = "Public hostname of the SPA, e.g. app.kifaru.example."
  type        = string
}

variable "api_domain" {
  description = "Public hostname of the API/WebSocket, e.g. api.kifaru.example."
  type        = string
}

variable "web_bucket_regional_domain_name" {
  description = "Regional domain name of the web S3 bucket."
  type        = string
}

variable "web_bucket_arn" {
  description = "ARN of the web S3 bucket (bucket policy is attached here so it can reference the distribution)."
  type        = string
}

variable "web_bucket_name" {
  description = "Name of the web S3 bucket."
  type        = string
}

variable "api_origin_domain" {
  description = "ALB origin hostname (api-origin.<domain>) with a valid regional certificate."
  type        = string
}

variable "origin_verify_header_value" {
  description = "Shared secret sent to the ALB in X-Origin-Verify."
  type        = string
  sensitive   = true
}

variable "price_class" {
  description = "CloudFront price class. PriceClass_All includes the Nairobi/Johannesburg/Cape Town PoPs; PriceClass_100 does not."
  type        = string
  default     = "PriceClass_All"
}

variable "waf_rate_limit" {
  description = "Requests per 5 minutes per IP before the rate rule blocks."
  type        = number
  default     = 2000
}

variable "waf_rate_limit_auth" {
  description = "Requests per 5 minutes per IP on /api/v1/auth/* (login brute-force protection)."
  type        = number
  default     = 100
}

variable "waf_log_retention_days" {
  description = "Retention of WAF logs in CloudWatch."
  type        = number
  default     = 30
}

variable "enable_waf_logging" {
  description = "Deliver WAF logs to CloudWatch Logs (log group name must start with aws-waf-logs-)."
  type        = bool
  default     = true
}

variable "tags" {
  description = "Tags applied to every resource."
  type        = map(string)
  default     = {}
}
