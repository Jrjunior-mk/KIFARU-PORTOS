output "cluster_name" {
  description = "ECS cluster name."
  value       = aws_ecs_cluster.this.name
}

output "cluster_arn" {
  description = "ECS cluster ARN."
  value       = aws_ecs_cluster.this.arn
}

output "service_names" {
  description = "Map service key => ECS service name."
  value       = { for k, s in aws_ecs_service.this : k => s.name }
}

output "ecr_repository_urls" {
  description = "Map image name (api, web) => ECR repository URL."
  value       = { for k, r in aws_ecr_repository.this : k => r.repository_url }
}

output "ecr_repository_arns" {
  description = "Map image name => ECR repository ARN."
  value       = { for k, r in aws_ecr_repository.this : k => r.arn }
}

output "alb_dns_name" {
  description = "ALB DNS name."
  value       = aws_lb.this.dns_name
}

output "alb_arn_suffix" {
  description = "ALB ARN suffix for CloudWatch metrics."
  value       = aws_lb.this.arn_suffix
}

output "alb_zone_id" {
  description = "ALB hosted zone ID."
  value       = aws_lb.this.zone_id
}

output "api_origin_domain" {
  description = "DNS name of the ALB origin record."
  value       = aws_route53_record.origin.fqdn
}

output "target_group_arn_suffixes" {
  description = "Map service key => target group ARN suffix (for alarms)."
  value       = { for k, tg in aws_lb_target_group.this : k => tg.arn_suffix }
}

output "tasks_security_group_id" {
  description = "Security group of the Fargate tasks (allow in RDS/Redis)."
  value       = aws_security_group.tasks.id
}

output "task_role_arn" {
  description = "Task role ARN."
  value       = aws_iam_role.task.arn
}

output "execution_role_arn" {
  description = "Execution role ARN."
  value       = aws_iam_role.execution.arn
}

output "migrate_task_definition_arn" {
  description = "Task definition for `alembic upgrade head` (run with aws ecs run-task)."
  value       = aws_ecs_task_definition.migrate.arn
}

output "migrate_task_definition_family" {
  description = "Family name of the migrate task definition."
  value       = aws_ecs_task_definition.migrate.family
}

output "seed_task_definition_arn" {
  description = "Task definition for demo seeding (null in prod)."
  value       = length(aws_ecs_task_definition.seed) > 0 ? aws_ecs_task_definition.seed[0].arn : null
}

output "pg_dump_task_definition_arn" {
  description = "Task definition for the scheduled pg_dump (null when disabled)."
  value       = length(aws_ecs_task_definition.pg_dump) > 0 ? aws_ecs_task_definition.pg_dump[0].arn : null
}

output "origin_verify_header_value" {
  description = "Shared secret CloudFront must send in X-Origin-Verify. Sensitive."
  value       = random_password.origin_verify.result
  sensitive   = true
}

output "log_group_names" {
  description = "CloudWatch log groups per service."
  value       = { for k, lg in aws_cloudwatch_log_group.service : k => lg.name }
}
