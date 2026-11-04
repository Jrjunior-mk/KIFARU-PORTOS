output "oidc_provider_arn" {
  description = "ARN of the GitHub OIDC provider in use."
  value       = local.oidc_arn
}

output "deploy_role_arn" {
  description = "Role for image push / ECS deploy / web sync. Store as the AWS_DEPLOY_ROLE_ARN GitHub variable."
  value       = aws_iam_role.deploy.arn
}

output "terraform_role_arn" {
  description = "Role for terraform apply in CI (null when not created). Store as the AWS_TERRAFORM_ROLE_ARN GitHub variable."
  value       = var.create_terraform_role ? aws_iam_role.terraform[0].arn : null
}
