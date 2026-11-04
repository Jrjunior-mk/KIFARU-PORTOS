# ---------------------------------------------------------------------------------------------------------------------
# edge: public entry points.
#   * ACM certificate in us-east-1 (CloudFront requirement) covering web + api hostnames, DNS-validated in Route 53
#   * WAF web ACL (CLOUDFRONT scope): AWS managed Common, Known-bad-inputs, IP-reputation rule groups + two rate rules
#   * CloudFront distribution `web`  : S3 origin via Origin Access Control, SPA fallback (403/404 -> /index.html)
#   * CloudFront distribution `api`  : ALB origin over HTTPS, caching disabled, all methods, WebSocket pass-through,
#                                      X-Origin-Verify header so the ALB only serves CloudFront
#   * Route 53 alias records (A + AAAA) for both hostnames
# ---------------------------------------------------------------------------------------------------------------------

locals {
  tags = merge(var.tags, { DataClass = "Public" })

  # AWS managed policy IDs (stable, documented by AWS)
  cache_policy_optimized   = "658327ea-f89d-4fab-a63d-7e88639e58f6" # CachingOptimized
  cache_policy_disabled    = "4135ea2d-6df8-44a3-9df3-4b5a84be39ad" # CachingDisabled
  origin_request_allviewer = "216adef6-5c7f-47e4-b989-5492eafa07d3" # AllViewer
  response_headers_sec     = "67f7725c-6f97-4210-82d7-5512b31e9d03" # SecurityHeadersPolicy
  cloudfront_zone_id       = "Z2FDTNDATAQYW2"
}

# --- ACM (us-east-1) ---------------------------------------------------------------------------------------------------

resource "aws_acm_certificate" "edge" {
  provider = aws.us_east_1

  domain_name               = var.web_domain
  subject_alternative_names = [var.api_domain]
  validation_method         = "DNS"
  tags                      = local.tags

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_route53_record" "edge_validation" {
  for_each = {
    for dvo in aws_acm_certificate.edge.domain_validation_options : dvo.domain_name => {
      name   = dvo.resource_record_name
      record = dvo.resource_record_value
      type   = dvo.resource_record_type
    }
  }

  zone_id         = var.route53_zone_id
  name            = each.value.name
  type            = each.value.type
  ttl             = 60
  records         = [each.value.record]
  allow_overwrite = true
}

resource "aws_acm_certificate_validation" "edge" {
  provider = aws.us_east_1

  certificate_arn         = aws_acm_certificate.edge.arn
  validation_record_fqdns = [for r in aws_route53_record.edge_validation : r.fqdn]
}

# --- WAF ---------------------------------------------------------------------------------------------------------------

resource "aws_wafv2_web_acl" "this" {
  provider = aws.us_east_1

  name        = "${var.name_prefix}-edge"
  description = "KIFARU PORTOS edge protection"
  scope       = "CLOUDFRONT"

  default_action {
    allow {}
  }

  rule {
    name     = "aws-common"
    priority = 10

    override_action {
      none {}
    }

    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesCommonRuleSet"
        vendor_name = "AWS"

        # SPA uploads (evidence images) can exceed the default 8 KB body inspection; keep the rule but let large bodies through.
        rule_action_override {
          name = "SizeRestrictions_BODY"
          action_to_use {
            count {}
          }
        }
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${var.name_prefix}-aws-common"
      sampled_requests_enabled   = true
    }
  }

  rule {
    name     = "aws-known-bad-inputs"
    priority = 20

    override_action {
      none {}
    }

    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesKnownBadInputsRuleSet"
        vendor_name = "AWS"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${var.name_prefix}-known-bad-inputs"
      sampled_requests_enabled   = true
    }
  }

  rule {
    name     = "aws-ip-reputation"
    priority = 30

    override_action {
      none {}
    }

    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesAmazonIpReputationList"
        vendor_name = "AWS"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${var.name_prefix}-ip-reputation"
      sampled_requests_enabled   = true
    }
  }

  rule {
    name     = "rate-limit-auth"
    priority = 40

    action {
      block {}
    }

    statement {
      rate_based_statement {
        limit              = var.waf_rate_limit_auth
        aggregate_key_type = "IP"

        scope_down_statement {
          byte_match_statement {
            search_string         = "/api/v1/auth/"
            positional_constraint = "STARTS_WITH"
            field_to_match {
              uri_path {}
            }
            text_transformation {
              priority = 0
              type     = "LOWERCASE"
            }
          }
        }
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${var.name_prefix}-rate-auth"
      sampled_requests_enabled   = true
    }
  }

  rule {
    name     = "rate-limit-global"
    priority = 50

    action {
      block {}
    }

    statement {
      rate_based_statement {
        limit              = var.waf_rate_limit
        aggregate_key_type = "IP"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${var.name_prefix}-rate-global"
      sampled_requests_enabled   = true
    }
  }

  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = "${var.name_prefix}-edge"
    sampled_requests_enabled   = true
  }

  tags = local.tags
}

resource "aws_cloudwatch_log_group" "waf" {
  count    = var.enable_waf_logging ? 1 : 0
  provider = aws.us_east_1

  name              = "aws-waf-logs-${var.name_prefix}-edge"
  retention_in_days = var.waf_log_retention_days
  tags              = local.tags
}

resource "aws_wafv2_web_acl_logging_configuration" "this" {
  count    = var.enable_waf_logging ? 1 : 0
  provider = aws.us_east_1

  resource_arn            = aws_wafv2_web_acl.this.arn
  log_destination_configs = [aws_cloudwatch_log_group.waf[0].arn]

  redacted_fields {
    single_header {
      name = "authorization"
    }
  }

  redacted_fields {
    single_header {
      name = "cookie"
    }
  }
}

# --- CloudFront: web (S3 + OAC) ----------------------------------------------------------------------------------------

resource "aws_cloudfront_origin_access_control" "web" {
  name                              = "${var.name_prefix}-web"
  description                       = "OAC for the KIFARU web bucket"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_cloudfront_distribution" "web" {
  enabled             = true
  is_ipv6_enabled     = true
  comment             = "${var.name_prefix} web (SPA)"
  default_root_object = "index.html"
  aliases             = [var.web_domain]
  price_class         = var.price_class
  http_version        = "http2and3"
  web_acl_id          = aws_wafv2_web_acl.this.arn

  origin {
    origin_id                = "s3-web"
    domain_name              = var.web_bucket_regional_domain_name
    origin_access_control_id = aws_cloudfront_origin_access_control.web.id
  }

  default_cache_behavior {
    target_origin_id           = "s3-web"
    viewer_protocol_policy     = "redirect-to-https"
    allowed_methods            = ["GET", "HEAD", "OPTIONS"]
    cached_methods             = ["GET", "HEAD"]
    compress                   = true
    cache_policy_id            = local.cache_policy_optimized
    response_headers_policy_id = local.response_headers_sec
  }

  # SPA client-side routing: unknown paths return the app shell.
  custom_error_response {
    error_code            = 403
    response_code         = 200
    response_page_path    = "/index.html"
    error_caching_min_ttl = 10
  }

  custom_error_response {
    error_code            = 404
    response_code         = 200
    response_page_path    = "/index.html"
    error_caching_min_ttl = 10
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    acm_certificate_arn      = aws_acm_certificate_validation.edge.certificate_arn
    ssl_support_method       = "sni-only"
    minimum_protocol_version = "TLSv1.2_2021"
  }

  tags = local.tags
}

data "aws_iam_policy_document" "web_bucket" {
  statement {
    sid     = "AllowCloudFrontOAC"
    actions = ["s3:GetObject"]
    principals {
      type        = "Service"
      identifiers = ["cloudfront.amazonaws.com"]
    }
    resources = ["${var.web_bucket_arn}/*"]
    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values   = [aws_cloudfront_distribution.web.arn]
    }
  }

  statement {
    sid     = "DenyInsecureTransport"
    effect  = "Deny"
    actions = ["s3:*"]
    principals {
      type        = "AWS"
      identifiers = ["*"]
    }
    resources = [var.web_bucket_arn, "${var.web_bucket_arn}/*"]
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "web" {
  bucket = var.web_bucket_name
  policy = data.aws_iam_policy_document.web_bucket.json
}

# --- CloudFront: api (ALB origin) ------------------------------------------------------------------------------------------

resource "aws_cloudfront_distribution" "api" {
  enabled         = true
  is_ipv6_enabled = true
  comment         = "${var.name_prefix} api + websocket"
  aliases         = [var.api_domain]
  price_class     = var.price_class
  http_version    = "http2and3"
  web_acl_id      = aws_wafv2_web_acl.this.arn

  origin {
    origin_id   = "alb-api"
    domain_name = var.api_origin_domain

    custom_origin_config {
      http_port                = 80
      https_port               = 443
      origin_protocol_policy   = "https-only"
      origin_ssl_protocols     = ["TLSv1.2"]
      origin_read_timeout      = 60
      origin_keepalive_timeout = 60
    }

    custom_header {
      name  = "X-Origin-Verify"
      value = var.origin_verify_header_value
    }
  }

  default_cache_behavior {
    target_origin_id         = "alb-api"
    viewer_protocol_policy   = "https-only"
    allowed_methods          = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
    cached_methods           = ["GET", "HEAD"]
    compress                 = true
    cache_policy_id          = local.cache_policy_disabled
    origin_request_policy_id = local.origin_request_allviewer
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    acm_certificate_arn      = aws_acm_certificate_validation.edge.certificate_arn
    ssl_support_method       = "sni-only"
    minimum_protocol_version = "TLSv1.2_2021"
  }

  tags = local.tags
}

# --- Route 53 ----------------------------------------------------------------------------------------------------------

resource "aws_route53_record" "web" {
  for_each = toset(["A", "AAAA"])

  zone_id = var.route53_zone_id
  name    = var.web_domain
  type    = each.value

  alias {
    name                   = aws_cloudfront_distribution.web.domain_name
    zone_id                = local.cloudfront_zone_id
    evaluate_target_health = false
  }
}

resource "aws_route53_record" "api" {
  for_each = toset(["A", "AAAA"])

  zone_id = var.route53_zone_id
  name    = var.api_domain
  type    = each.value

  alias {
    name                   = aws_cloudfront_distribution.api.domain_name
    zone_id                = local.cloudfront_zone_id
    evaluate_target_health = false
  }
}
