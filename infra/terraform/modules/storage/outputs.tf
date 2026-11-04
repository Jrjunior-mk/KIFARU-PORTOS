output "objects_bucket_name" {
  description = "Objects bucket name (KIFARU_S3_BUCKET)."
  value       = aws_s3_bucket.objects.bucket
}

output "objects_bucket_arn" {
  description = "Objects bucket ARN."
  value       = aws_s3_bucket.objects.arn
}

output "backups_bucket_name" {
  description = "Backups bucket name (pg_dump target)."
  value       = aws_s3_bucket.backups.bucket
}

output "backups_bucket_arn" {
  description = "Backups bucket ARN."
  value       = aws_s3_bucket.backups.arn
}

output "web_bucket_name" {
  description = "Web (SPA) bucket name."
  value       = aws_s3_bucket.web.bucket
}

output "web_bucket_arn" {
  description = "Web bucket ARN."
  value       = aws_s3_bucket.web.arn
}

output "web_bucket_regional_domain_name" {
  description = "Regional domain name of the web bucket (CloudFront origin)."
  value       = aws_s3_bucket.web.bucket_regional_domain_name
}

output "access_logs_bucket_name" {
  description = "ALB access log bucket."
  value       = aws_s3_bucket.logs.bucket
}

output "kms_key_arn" {
  description = "KMS key used for objects/backups encryption (task roles need kms:GenerateDataKey/Decrypt)."
  value       = aws_kms_key.s3.arn
}

output "dr_kms_key_arn" {
  description = "KMS key in the DR region."
  value       = aws_kms_key.s3_dr.arn
}

output "objects_dr_bucket_name" {
  description = "DR replica of the objects bucket (null when replication is disabled)."
  value       = var.enable_replication ? aws_s3_bucket.objects_dr[0].bucket : null
}

output "backups_dr_bucket_name" {
  description = "DR replica of the backups bucket (null when replication is disabled)."
  value       = var.enable_replication ? aws_s3_bucket.backups_dr[0].bucket : null
}
