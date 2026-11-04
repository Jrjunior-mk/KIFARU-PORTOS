# ---------------------------------------------------------------------------------------------------------------------
# KIFARU PORTOS environment root. IDENTICAL across envs/*; differences live in terraform.tfvars.
# Module wiring (top to bottom): network -> secrets -> storage -> queue -> rds/redis -> ecs -> edge -> iot -> monitoring
# -> ci_oidc.
# ---------------------------------------------------------------------------------------------------------------------

locals {
  name_prefix        = "kifaru-${var.env}"
  secret_path_prefix = "kifaru/${var.env}"

  default_tags = merge({
    Project   = "KIFARU-PORTOS"
    Env       = var.env
    ManagedBy = "terraform"
    Root      = "infra/terraform/envs/${var.env}"
  }, var.extra_tags)

  mqtt_host = var.iot_mode == "iot_core" ? module.iot[0].mqtt_endpoint : (var.iot_mode == "emqx" ? module.iot_emqx[0].mqtt_endpoint : "")

  app_environment = {
    KIFARU_LOG_LEVEL        = var.log_level
    KIFARU_S3_BUCKET        = module.storage.objects_bucket_name
    KIFARU_PUBLIC_BASE_URL  = "https://${var.web_domain}"
    KIFARU_CORS_ORIGINS     = jsonencode(["https://${var.web_domain}"])
    KIFARU_SIGNING_KEY_ID   = var.signing_key_id
    KIFARU_EVENTS_QUEUE_URL = module.queue.events_queue_url
    KIFARU_JOBS_QUEUE_URL   = module.queue.jobs_queue_url
    KIFARU_MQTT_HOST        = local.mqtt_host
    KIFARU_MQTT_PORT        = "8883"
    KIFARU_MQTT_CLIENT_ID   = "${local.name_prefix}-ingest"
    KIFARU_IOT_MODE         = var.iot_mode
  }

  app_secrets = merge(
    {
      KIFARU_JWT_SECRET       = module.secrets.jwt_secret_arn
      KIFARU_SIGNING_SEED_B64 = module.secrets.signing_seed_secret_arn
      KIFARU_DATABASE_URL     = module.rds.database_url_secret_arn
      KIFARU_REDIS_URL        = module.redis.redis_url_secret_arn
    },
    { for k in module.secrets.app_secret_keys : k => "${module.secrets.app_secrets_arn}:${k}::" },
  )

  secret_arns = [
    module.secrets.jwt_secret_arn,
    module.secrets.signing_seed_secret_arn,
    module.secrets.app_secrets_arn,
    module.rds.database_url_secret_arn,
    module.rds.database_secret_arn,
    module.redis.redis_url_secret_arn,
  ]
}

# --- Network -----------------------------------------------------------------------------------------------------------

module "network" {
  source = "../../modules/network"

  name_prefix                = local.name_prefix
  vpc_cidr                   = var.vpc_cidr
  az_count                   = 2
  single_nat_gateway         = var.single_nat_gateway
  enable_interface_endpoints = var.enable_interface_endpoints
  flow_log_retention_days    = var.log_retention_days
}

# --- Secrets -----------------------------------------------------------------------------------------------------------

module "secrets" {
  source = "../../modules/secrets"

  name_prefix             = local.name_prefix
  secret_path_prefix      = local.secret_path_prefix
  signing_key_id          = var.signing_key_id
  recovery_window_in_days = var.secrets_recovery_window_in_days
}

# --- Storage -----------------------------------------------------------------------------------------------------------

module "storage" {
  source = "../../modules/storage"
  providers = {
    aws    = aws
    aws.dr = aws.dr
  }

  name_prefix        = local.name_prefix
  enable_replication = var.s3_enable_replication
  force_destroy      = var.s3_force_destroy
}

# --- Queues ------------------------------------------------------------------------------------------------------------

module "queue" {
  source = "../../modules/queue"

  name_prefix = local.name_prefix
  kms_key_arn = module.secrets.kms_key_arn
}

# --- Database ----------------------------------------------------------------------------------------------------------

module "rds" {
  source = "../../modules/rds"
  providers = {
    aws    = aws
    aws.dr = aws.dr
  }

  name_prefix                            = local.name_prefix
  secret_path_prefix                     = local.secret_path_prefix
  vpc_id                                 = module.network.vpc_id
  subnet_ids                             = module.network.private_subnet_ids
  allowed_security_group_ids             = [module.ecs.tasks_security_group_id]
  instance_class                         = var.rds_instance_class
  allocated_storage                      = var.rds_allocated_storage
  max_allocated_storage                  = var.rds_max_allocated_storage
  multi_az                               = var.rds_multi_az
  deletion_protection                    = var.rds_deletion_protection
  skip_final_snapshot                    = var.rds_skip_final_snapshot
  enable_cross_region_backup_replication = var.rds_cross_region_backup_replication
  rotation_lambda_arn                    = var.rds_rotation_lambda_arn
  secrets_kms_key_arn                    = module.secrets.kms_key_arn
  recovery_window_in_days                = var.secrets_recovery_window_in_days
}

# --- Redis -------------------------------------------------------------------------------------------------------------

module "redis" {
  source = "../../modules/redis"

  name_prefix                = local.name_prefix
  secret_path_prefix         = local.secret_path_prefix
  vpc_id                     = module.network.vpc_id
  subnet_ids                 = module.network.private_subnet_ids
  allowed_security_group_ids = [module.ecs.tasks_security_group_id]
  node_type                  = var.redis_node_type
  num_cache_clusters         = var.redis_num_cache_clusters
  snapshot_retention_limit   = var.redis_snapshot_retention_limit
  secrets_kms_key_arn        = module.secrets.kms_key_arn
  recovery_window_in_days    = var.secrets_recovery_window_in_days
}

# --- Compute -----------------------------------------------------------------------------------------------------------

module "ecs" {
  source = "../../modules/ecs"

  name_prefix                = local.name_prefix
  env                        = var.env
  vpc_id                     = module.network.vpc_id
  public_subnet_ids          = module.network.public_subnet_ids
  private_subnet_ids         = module.network.private_subnet_ids
  route53_zone_id            = var.route53_zone_id
  api_origin_domain          = var.api_origin_domain
  restrict_alb_to_cloudfront = var.restrict_alb_to_cloudfront
  image_tag                  = var.image_tag
  cpu_architecture           = var.cpu_architecture
  use_fargate_spot           = var.use_fargate_spot
  services                   = var.services
  app_environment            = local.app_environment
  app_secrets                = local.app_secrets
  secret_arns                = local.secret_arns
  secrets_kms_key_arn        = module.secrets.kms_key_arn
  objects_bucket_arn         = module.storage.objects_bucket_arn
  backups_bucket_arn         = module.storage.backups_bucket_arn
  backups_bucket_name        = module.storage.backups_bucket_name
  s3_kms_key_arn             = module.storage.kms_key_arn
  queue_arns                 = module.queue.all_queue_arns
  access_logs_bucket         = module.storage.access_logs_bucket_name
  database_secret_arn        = module.rds.database_secret_arn
  enable_pg_dump             = var.enable_pg_dump
  pg_dump_schedule           = var.pg_dump_schedule
  create_seed_task           = var.create_seed_task
  log_retention_days         = var.log_retention_days
}

# --- Edge --------------------------------------------------------------------------------------------------------------

module "edge" {
  source = "../../modules/edge"
  providers = {
    aws           = aws
    aws.us_east_1 = aws.us_east_1
  }

  name_prefix                     = local.name_prefix
  route53_zone_id                 = var.route53_zone_id
  web_domain                      = var.web_domain
  api_domain                      = var.api_domain
  web_bucket_regional_domain_name = module.storage.web_bucket_regional_domain_name
  web_bucket_arn                  = module.storage.web_bucket_arn
  web_bucket_name                 = module.storage.web_bucket_name
  api_origin_domain               = module.ecs.api_origin_domain
  origin_verify_header_value      = module.ecs.origin_verify_header_value
  price_class                     = var.cloudfront_price_class
  waf_rate_limit                  = var.waf_rate_limit
  waf_rate_limit_auth             = var.waf_rate_limit_auth
  waf_log_retention_days          = var.log_retention_days
}

# --- IoT ---------------------------------------------------------------------------------------------------------------

module "iot" {
  source = "../../modules/iot"
  count  = var.iot_mode == "iot_core" ? 1 : 0

  name_prefix        = local.name_prefix
  events_queue_arn   = module.queue.events_queue_arn
  events_queue_url   = module.queue.events_queue_url
  log_retention_days = var.log_retention_days
  enable_iot_logging = var.enable_iot_logging
}

module "iot_emqx" {
  source = "../../modules/iot_emqx_fallback"
  count  = var.iot_mode == "emqx" ? 1 : 0

  name_prefix        = local.name_prefix
  vpc_id             = module.network.vpc_id
  public_subnet_ids  = module.network.public_subnet_ids
  private_subnet_ids = module.network.private_subnet_ids
  cluster_arn        = module.ecs.cluster_arn
  execution_role_arn = module.ecs.execution_role_arn
  certificate_arn    = var.emqx_certificate_arn
  log_retention_days = var.log_retention_days
}

# --- Monitoring --------------------------------------------------------------------------------------------------------

module "monitoring" {
  source = "../../modules/monitoring"

  name_prefix                = local.name_prefix
  alarm_email                = var.alarm_email
  alb_arn_suffix             = module.ecs.alb_arn_suffix
  target_group_arn_suffixes  = module.ecs.target_group_arn_suffixes
  ecs_cluster_name           = module.ecs.cluster_name
  ecs_service_names          = module.ecs.service_names
  rds_instance_identifier    = module.rds.instance_identifier
  rds_max_connections        = var.rds_max_connections_alarm
  redis_replication_group_id = module.redis.replication_group_id
  dlq_names                  = module.queue.dlq_names
  events_queue_name          = module.queue.events_queue_name
}

# --- CI/CD federation ----------------------------------------------------------------------------------------------------

module "ci_oidc" {
  source = "../../modules/ci_oidc"

  name_prefix                  = local.name_prefix
  github_org                   = var.github_org
  github_repo                  = var.github_repo
  allowed_subjects             = var.github_allowed_subjects
  create_oidc_provider         = var.create_oidc_provider
  ecr_repository_arns          = values(module.ecs.ecr_repository_arns)
  ecs_cluster_arn              = module.ecs.cluster_arn
  ecs_task_role_arns           = [module.ecs.task_role_arn, module.ecs.execution_role_arn]
  web_bucket_arn               = module.storage.web_bucket_arn
  cloudfront_distribution_arns = [module.edge.web_distribution_arn]
  state_bucket_arn             = var.state_bucket_arn
  state_lock_table_arn         = var.state_lock_table_arn
}
