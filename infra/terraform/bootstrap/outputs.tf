output "state_bucket_name" {
  description = "Use as `bucket` in each env's backend.hcl."
  value       = aws_s3_bucket.state.bucket
}

output "state_bucket_arn" {
  description = "Pass as state_bucket_arn to each env root (ci_oidc policies)."
  value       = aws_s3_bucket.state.arn
}

output "lock_table_name" {
  description = "Use as `dynamodb_table` in each env's backend.hcl."
  value       = aws_dynamodb_table.lock.name
}

output "lock_table_arn" {
  description = "Pass as state_lock_table_arn to each env root."
  value       = aws_dynamodb_table.lock.arn
}

output "state_kms_key_arn" {
  description = "Use as `kms_key_id` in each env's backend.hcl."
  value       = aws_kms_key.state.arn
}
