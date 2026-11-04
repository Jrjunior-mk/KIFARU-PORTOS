output "kms_key_arn" {
  description = "KMS key protecting the application secrets."
  value       = aws_kms_key.secrets.arn
}

output "jwt_secret_arn" {
  description = "ARN of the JWT secret (inject as KIFARU_JWT_SECRET)."
  value       = aws_secretsmanager_secret.jwt.arn
}

output "signing_seed_secret_arn" {
  description = "ARN of the Ed25519 signing seed secret (inject as KIFARU_SIGNING_SEED_B64)."
  value       = aws_secretsmanager_secret.signing_seed.arn
}

output "app_secrets_arn" {
  description = "ARN of the JSON secret holding third-party credentials."
  value       = aws_secretsmanager_secret.app.arn
}

output "app_secret_keys" {
  description = "Keys present in the app-secrets JSON (used to build ECS secret references)."
  value       = var.external_adapter_keys
}

output "jwt_secret_value" {
  description = "The generated JWT secret. Sensitive; only for break-glass output, never logged."
  value       = random_password.jwt.result
  sensitive   = true
}

output "signing_seed_b64" {
  description = "The generated signing seed (base64). Sensitive."
  value       = random_bytes.signing_seed.base64
  sensitive   = true
}
