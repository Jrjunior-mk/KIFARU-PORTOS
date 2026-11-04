output "web_url" {
  description = "Public SPA URL."
  value       = module.edge.web_url
}

output "api_url" {
  description = "Public API URL."
  value       = module.edge.api_url
}

output "ecr_repository_urls" {
  description = "ECR repositories (api, web) the deploy workflow pushes to."
  value       = module.ecs.ecr_repository_urls
}

output "ecs_cluster_name" {
  description = "ECS cluster name."
  value       = module.ecs.cluster_name
}

output "ecs_service_names" {
  description = "ECS service names."
  value       = module.ecs.service_names
}

output "migrate_task_definition_family" {
  description = "Run `aws ecs run-task` with this family to apply Alembic migrations."
  value       = module.ecs.migrate_task_definition_family
}

output "seed_task_definition_arn" {
  description = "Demo-seed task definition (null in prod)."
  value       = module.ecs.seed_task_definition_arn
}

output "private_subnet_ids" {
  description = "Subnets for run-task network configuration."
  value       = module.network.private_subnet_ids
}

output "tasks_security_group_id" {
  description = "Security group for run-task network configuration."
  value       = module.ecs.tasks_security_group_id
}

output "web_bucket_name" {
  description = "Bucket to sync apps/web/dist into."
  value       = module.storage.web_bucket_name
}

output "web_distribution_id" {
  description = "CloudFront distribution to invalidate after a web deploy."
  value       = module.edge.web_distribution_id
}

output "objects_bucket_name" {
  description = "Application objects bucket."
  value       = module.storage.objects_bucket_name
}

output "backups_bucket_name" {
  description = "pg_dump target bucket."
  value       = module.storage.backups_bucket_name
}

output "rds_instance_identifier" {
  description = "RDS identifier (snapshots, DR)."
  value       = module.rds.instance_identifier
}

output "mqtt_endpoint" {
  description = "MQTT endpoint for station gateways (IoT Core ATS endpoint or EMQX NLB); empty when iot_mode = none."
  value       = local.mqtt_host
}

output "iot_thing_type_name" {
  description = "IoT thing type for gateway registration (null unless iot_mode = iot_core)."
  value       = var.iot_mode == "iot_core" ? module.iot[0].thing_type_name : null
}

output "iot_device_policy_name" {
  description = "IoT policy to attach to gateway certificates (null unless iot_mode = iot_core)."
  value       = var.iot_mode == "iot_core" ? module.iot[0].device_policy_name : null
}

output "alarm_topic_arn" {
  description = "SNS topic for alarms."
  value       = module.monitoring.sns_topic_arn
}

output "dashboard_name" {
  description = "CloudWatch dashboard."
  value       = module.monitoring.dashboard_name
}

output "github_deploy_role_arn" {
  description = "Set as GitHub variable AWS_DEPLOY_ROLE_ARN for this environment."
  value       = module.ci_oidc.deploy_role_arn
}

output "github_terraform_role_arn" {
  description = "Set as GitHub variable AWS_TERRAFORM_ROLE_ARN for this environment."
  value       = module.ci_oidc.terraform_role_arn
}
