output "web_distribution_id" {
  description = "CloudFront distribution ID for the SPA (invalidate after each web deploy)."
  value       = aws_cloudfront_distribution.web.id
}

output "web_distribution_arn" {
  description = "CloudFront distribution ARN for the SPA."
  value       = aws_cloudfront_distribution.web.arn
}

output "web_distribution_domain_name" {
  description = "CloudFront domain of the SPA distribution."
  value       = aws_cloudfront_distribution.web.domain_name
}

output "api_distribution_id" {
  description = "CloudFront distribution ID for the API."
  value       = aws_cloudfront_distribution.api.id
}

output "api_distribution_domain_name" {
  description = "CloudFront domain of the API distribution."
  value       = aws_cloudfront_distribution.api.domain_name
}

output "web_url" {
  description = "Public URL of the SPA."
  value       = "https://${var.web_domain}"
}

output "api_url" {
  description = "Public URL of the API."
  value       = "https://${var.api_domain}"
}

output "waf_web_acl_arn" {
  description = "WAF web ACL ARN."
  value       = aws_wafv2_web_acl.this.arn
}

output "certificate_arn" {
  description = "us-east-1 ACM certificate ARN."
  value       = aws_acm_certificate_validation.edge.certificate_arn
}
