# ---------------------------------------------------------------------------------------------------------------------
# ecs: ECR repositories, Fargate cluster, ALB (HTTPS, regional ACM cert), one service per entry in var.services,
# a one-off `migrate` task definition (alembic upgrade head), an optional `seed` task and a scheduled `pg_dump` task.
#
# Traffic path: CloudFront (edge module) -> ALB :443 -> listener rules match X-Origin-Verify header + path -> target group.
# Requests that bypass CloudFront (no/incorrect header) receive 403 from the listener default action.
# ---------------------------------------------------------------------------------------------------------------------

data "aws_region" "current" {}
data "aws_caller_identity" "current" {}

data "aws_ec2_managed_prefix_list" "cloudfront" {
  name = "com.amazonaws.global.cloudfront.origin-facing"
}

locals {
  tags   = merge(var.tags, { DataClass = "Internal" })
  region = data.aws_region.current.name
  acct   = data.aws_caller_identity.current.account_id

  api_image = "${aws_ecr_repository.this["api"].repository_url}:${var.image_tag}"

  lb_services = { for k, s in var.services : k => s if s.attach_alb }

  base_env = {
    KIFARU_ENV       = var.env
    KIFARU_S3_REGION = local.region
    PYTHONUNBUFFERED = "1"
  }

  environment = [for k, v in merge(local.base_env, var.app_environment) : { name = k, value = v }]
  secrets     = [for k, v in var.app_secrets : { name = k, valueFrom = v }]

  http_health_check = {
    command     = ["CMD-SHELL", "python -c \"import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).status == 200 else 1)\""]
    interval    = 30
    timeout     = 5
    retries     = 3
    startPeriod = 30
  }

  pg_dump_script = <<-EOT
    set -eu
    TS=$(date -u +%Y%m%dT%H%M%SZ)
    FILE="/tmp/kifaru-$${KIFARU_ENV}-$${TS}.dump"
    pg_dump --format=custom --compress=6 --no-owner --no-privileges --file "$FILE"
    python - "$FILE" <<'PY'
    import os, sys, boto3
    path = sys.argv[1]
    key = "pgdump/" + os.environ["KIFARU_ENV"] + "/" + os.path.basename(path)
    boto3.client("s3").upload_file(path, os.environ["BACKUP_BUCKET"], key,
        ExtraArgs={"ServerSideEncryption": "aws:kms", "SSEKMSKeyId": os.environ["BACKUP_KMS_KEY_ARN"]})
    print("uploaded s3://" + os.environ["BACKUP_BUCKET"] + "/" + key)
    PY
  EOT
}

# --- ECR ---------------------------------------------------------------------------------------------------------------

resource "aws_ecr_repository" "this" {
  for_each = toset(["api", "web"])

  name                 = "${var.name_prefix}/${each.key}"
  image_tag_mutability = "IMMUTABLE"
  force_delete         = var.env == "dev"

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }

  tags = local.tags
}

resource "aws_ecr_lifecycle_policy" "this" {
  for_each = aws_ecr_repository.this

  repository = each.value.name
  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Expire untagged images after 7 days"
        selection = {
          tagStatus   = "untagged"
          countType   = "sinceImagePushed"
          countUnit   = "days"
          countNumber = 7
        }
        action = { type = "expire" }
      },
      {
        rulePriority = 2
        description  = "Keep the last ${var.ecr_keep_images} tagged images"
        selection = {
          tagStatus      = "tagged"
          tagPatternList = ["*"]
          countType      = "imageCountMoreThan"
          countNumber    = var.ecr_keep_images
        }
        action = { type = "expire" }
      },
    ]
  })
}

# --- Cluster -----------------------------------------------------------------------------------------------------------

resource "aws_ecs_cluster" "this" {
  name = var.name_prefix

  setting {
    name  = "containerInsights"
    value = "enabled"
  }

  tags = local.tags
}

resource "aws_ecs_cluster_capacity_providers" "this" {
  cluster_name       = aws_ecs_cluster.this.name
  capacity_providers = ["FARGATE", "FARGATE_SPOT"]

  default_capacity_provider_strategy {
    capacity_provider = "FARGATE"
    weight            = 1
    base              = 1
  }
}

# --- Logs --------------------------------------------------------------------------------------------------------------

resource "aws_cloudwatch_log_group" "service" {
  for_each = var.services

  name              = "/kifaru/${var.name_prefix}/${each.key}"
  retention_in_days = var.log_retention_days
  tags              = local.tags
}

resource "aws_cloudwatch_log_group" "ops" {
  for_each = toset(["migrate", "seed", "pg-dump"])

  name              = "/kifaru/${var.name_prefix}/${each.key}"
  retention_in_days = var.log_retention_days
  tags              = local.tags
}

# --- IAM: execution role -----------------------------------------------------------------------------------------------

data "aws_iam_policy_document" "ecs_tasks_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = ["arn:aws:ecs:${local.region}:${local.acct}:*"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.acct]
    }
  }
}

resource "aws_iam_role" "execution" {
  name               = "${var.name_prefix}-ecs-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
  tags               = local.tags
}

resource "aws_iam_role_policy_attachment" "execution_managed" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

data "aws_iam_policy_document" "execution_secrets" {
  statement {
    sid       = "ReadSecrets"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = var.secret_arns
  }

  statement {
    sid       = "DecryptSecrets"
    actions   = ["kms:Decrypt"]
    resources = [var.secrets_kms_key_arn]
  }
}

resource "aws_iam_role_policy" "execution_secrets" {
  name   = "read-secrets"
  role   = aws_iam_role.execution.id
  policy = data.aws_iam_policy_document.execution_secrets.json
}

# --- IAM: task role ----------------------------------------------------------------------------------------------------

resource "aws_iam_role" "task" {
  name               = "${var.name_prefix}-ecs-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
  tags               = local.tags
}

data "aws_iam_policy_document" "task" {
  statement {
    sid       = "ObjectsBucketList"
    actions   = ["s3:ListBucket", "s3:GetBucketLocation"]
    resources = [var.objects_bucket_arn, var.backups_bucket_arn]
  }

  statement {
    sid = "ObjectsReadWrite"
    actions = [
      "s3:GetObject",
      "s3:GetObjectVersion",
      "s3:PutObject",
      "s3:PutObjectRetention",
      "s3:GetObjectRetention",
      "s3:DeleteObject",
      "s3:AbortMultipartUpload",
    ]
    resources = ["${var.objects_bucket_arn}/*"]
  }

  statement {
    sid       = "BackupsWrite"
    actions   = ["s3:PutObject", "s3:AbortMultipartUpload"]
    resources = ["${var.backups_bucket_arn}/*"]
  }

  statement {
    sid       = "S3Kms"
    actions   = ["kms:GenerateDataKey", "kms:Decrypt", "kms:Encrypt"]
    resources = [var.s3_kms_key_arn]
  }

  statement {
    sid = "Queues"
    actions = [
      "sqs:SendMessage",
      "sqs:ReceiveMessage",
      "sqs:DeleteMessage",
      "sqs:ChangeMessageVisibility",
      "sqs:GetQueueAttributes",
      "sqs:GetQueueUrl",
    ]
    resources = var.queue_arns
  }

  statement {
    sid = "EcsExec"
    actions = [
      "ssmmessages:CreateControlChannel",
      "ssmmessages:CreateDataChannel",
      "ssmmessages:OpenControlChannel",
      "ssmmessages:OpenDataChannel",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "task" {
  name   = "application"
  role   = aws_iam_role.task.id
  policy = data.aws_iam_policy_document.task.json
}

# --- Security groups ---------------------------------------------------------------------------------------------------

resource "aws_security_group" "alb" {
  name        = "${var.name_prefix}-alb"
  description = "Public ALB"
  vpc_id      = var.vpc_id
  tags        = merge(local.tags, { Name = "${var.name_prefix}-alb" })
}

resource "aws_vpc_security_group_ingress_rule" "alb_https_cloudfront" {
  count = var.restrict_alb_to_cloudfront ? 1 : 0

  security_group_id = aws_security_group.alb.id
  description       = "HTTPS from CloudFront origin-facing ranges"
  from_port         = 443
  to_port           = 443
  ip_protocol       = "tcp"
  prefix_list_id    = data.aws_ec2_managed_prefix_list.cloudfront.id
}

resource "aws_vpc_security_group_ingress_rule" "alb_https_any" {
  count = var.restrict_alb_to_cloudfront ? 0 : 1

  security_group_id = aws_security_group.alb.id
  description       = "HTTPS from anywhere (dev)"
  from_port         = 443
  to_port           = 443
  ip_protocol       = "tcp"
  cidr_ipv4         = "0.0.0.0/0"
}

resource "aws_vpc_security_group_egress_rule" "alb" {
  security_group_id = aws_security_group.alb.id
  description       = "To tasks"
  ip_protocol       = "-1"
  cidr_ipv4         = "0.0.0.0/0"
}

resource "aws_security_group" "tasks" {
  name        = "${var.name_prefix}-tasks"
  description = "Fargate tasks"
  vpc_id      = var.vpc_id
  tags        = merge(local.tags, { Name = "${var.name_prefix}-tasks" })
}

resource "aws_vpc_security_group_ingress_rule" "tasks_from_alb" {
  security_group_id            = aws_security_group.tasks.id
  description                  = "HTTP from ALB"
  from_port                    = 8000
  to_port                      = 8000
  ip_protocol                  = "tcp"
  referenced_security_group_id = aws_security_group.alb.id
}

resource "aws_vpc_security_group_egress_rule" "tasks" {
  security_group_id = aws_security_group.tasks.id
  description       = "All egress (AWS APIs via endpoints/NAT, RDS, Redis)"
  ip_protocol       = "-1"
  cidr_ipv4         = "0.0.0.0/0"
}

# --- Regional ACM certificate for the ALB origin ---------------------------------------------------------------------------

resource "aws_acm_certificate" "origin" {
  domain_name       = var.api_origin_domain
  validation_method = "DNS"
  tags              = local.tags

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_route53_record" "origin_validation" {
  for_each = {
    for dvo in aws_acm_certificate.origin.domain_validation_options : dvo.domain_name => {
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

resource "aws_acm_certificate_validation" "origin" {
  certificate_arn         = aws_acm_certificate.origin.arn
  validation_record_fqdns = [for r in aws_route53_record.origin_validation : r.fqdn]
}

# --- ALB ---------------------------------------------------------------------------------------------------------------

resource "random_password" "origin_verify" {
  length  = 40
  special = false
}

resource "aws_lb" "this" {
  name                       = "${var.name_prefix}-alb"
  load_balancer_type         = "application"
  internal                   = false
  security_groups            = [aws_security_group.alb.id]
  subnets                    = var.public_subnet_ids
  drop_invalid_header_fields = true
  idle_timeout               = 120 # WebSocket keep-alive headroom
  enable_deletion_protection = var.env == "prod"

  access_logs {
    bucket  = var.access_logs_bucket
    prefix  = "alb"
    enabled = true
  }

  tags = merge(local.tags, { Name = "${var.name_prefix}-alb" })
}

resource "aws_route53_record" "origin" {
  zone_id = var.route53_zone_id
  name    = var.api_origin_domain
  type    = "A"

  alias {
    name                   = aws_lb.this.dns_name
    zone_id                = aws_lb.this.zone_id
    evaluate_target_health = true
  }
}

resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.this.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = aws_acm_certificate_validation.origin.certificate_arn

  default_action {
    type = "fixed-response"
    fixed_response {
      content_type = "application/json"
      message_body = "{\"detail\":\"forbidden\"}"
      status_code  = "403"
    }
  }

  tags = local.tags
}

resource "aws_lb_target_group" "this" {
  for_each = local.lb_services

  name                 = substr("${var.name_prefix}-${each.key}", 0, 32)
  port                 = each.value.container_port
  protocol             = "HTTP"
  target_type          = "ip"
  vpc_id               = var.vpc_id
  deregistration_delay = 30

  health_check {
    enabled             = true
    path                = each.value.health_check_path
    matcher             = "200"
    interval            = 30
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }

  stickiness {
    type    = "lb_cookie"
    enabled = false
  }

  tags = local.tags
}

resource "aws_lb_listener_rule" "this" {
  for_each = local.lb_services

  listener_arn = aws_lb_listener.https.arn
  priority     = each.value.priority

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.this[each.key].arn
  }

  condition {
    http_header {
      http_header_name = "X-Origin-Verify"
      values           = [random_password.origin_verify.result]
    }
  }

  dynamic "condition" {
    for_each = length(each.value.path_patterns) > 0 ? [1] : []
    content {
      path_pattern {
        values = each.value.path_patterns
      }
    }
  }

  tags = local.tags
}

# --- Task definitions & services -----------------------------------------------------------------------------------------

resource "aws_ecs_task_definition" "service" {
  for_each = var.services

  family                   = "${var.name_prefix}-${each.key}"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = each.value.cpu
  memory                   = each.value.memory
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = var.cpu_architecture
  }

  container_definitions = jsonencode([
    {
      name                   = each.key
      image                  = local.api_image
      essential              = true
      command                = each.value.command
      portMappings           = each.value.attach_alb ? [{ containerPort = each.value.container_port, protocol = "tcp" }] : []
      environment            = concat(local.environment, [{ name = "KIFARU_SERVICE_ROLE", value = each.key }])
      secrets                = local.secrets
      healthCheck            = each.value.attach_alb ? local.http_health_check : null
      readonlyRootFilesystem = false
      linuxParameters = {
        initProcessEnabled = true
      }
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.service[each.key].name
          awslogs-region        = local.region
          awslogs-stream-prefix = each.key
        }
      }
    }
  ])

  tags = local.tags
}

resource "aws_ecs_service" "this" {
  for_each = var.services

  name                   = "${var.name_prefix}-${each.key}"
  cluster                = aws_ecs_cluster.this.id
  task_definition        = aws_ecs_task_definition.service[each.key].arn
  desired_count          = each.value.desired_count
  launch_type            = var.use_fargate_spot ? null : "FARGATE"
  platform_version       = "LATEST"
  enable_execute_command = true
  propagate_tags         = "SERVICE"

  health_check_grace_period_seconds = each.value.attach_alb ? 60 : null

  dynamic "capacity_provider_strategy" {
    for_each = var.use_fargate_spot ? [1] : []
    content {
      capacity_provider = "FARGATE_SPOT"
      weight            = 1
    }
  }

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [aws_security_group.tasks.id]
    assign_public_ip = false
  }

  dynamic "load_balancer" {
    for_each = each.value.attach_alb ? [1] : []
    content {
      target_group_arn = aws_lb_target_group.this[each.key].arn
      container_name   = each.key
      container_port   = each.value.container_port
    }
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200

  lifecycle {
    ignore_changes = [desired_count] # managed by Application Auto Scaling
  }

  tags       = local.tags
  depends_on = [aws_lb_listener_rule.this]
}

# --- Autoscaling -------------------------------------------------------------------------------------------------------

resource "aws_appautoscaling_target" "this" {
  for_each = var.services

  service_namespace  = "ecs"
  resource_id        = "service/${aws_ecs_cluster.this.name}/${aws_ecs_service.this[each.key].name}"
  scalable_dimension = "ecs:service:DesiredCount"
  min_capacity       = each.value.min_count
  max_capacity       = each.value.max_count
  tags               = local.tags
}

resource "aws_appautoscaling_policy" "cpu" {
  for_each = var.services

  name               = "${var.name_prefix}-${each.key}-cpu"
  policy_type        = "TargetTrackingScaling"
  service_namespace  = aws_appautoscaling_target.this[each.key].service_namespace
  resource_id        = aws_appautoscaling_target.this[each.key].resource_id
  scalable_dimension = aws_appautoscaling_target.this[each.key].scalable_dimension

  target_tracking_scaling_policy_configuration {
    target_value       = each.value.cpu_target
    scale_in_cooldown  = 300
    scale_out_cooldown = 60

    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
  }
}

# --- One-off: migrate (alembic upgrade head) ------------------------------------------------------------------------------

resource "aws_ecs_task_definition" "migrate" {
  family                   = "${var.name_prefix}-migrate"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 512
  memory                   = 1024
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = var.cpu_architecture
  }

  container_definitions = jsonencode([
    {
      name        = "migrate"
      image       = local.api_image
      essential   = true
      command     = ["alembic", "upgrade", "head"]
      environment = local.environment
      secrets     = local.secrets
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.ops["migrate"].name
          awslogs-region        = local.region
          awslogs-stream-prefix = "migrate"
        }
      }
    }
  ])

  tags = local.tags
}

# --- One-off: seed demo data (never created in prod) --------------------------------------------------------------------

resource "aws_ecs_task_definition" "seed" {
  count = var.create_seed_task && var.env != "prod" ? 1 : 0

  family                   = "${var.name_prefix}-seed"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 512
  memory                   = 1024
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = var.cpu_architecture
  }

  container_definitions = jsonencode([
    {
      name        = "seed"
      image       = local.api_image
      essential   = true
      command     = ["python", "-m", "kifaru.seed", "--quiet"]
      environment = local.environment
      secrets     = local.secrets
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.ops["seed"].name
          awslogs-region        = local.region
          awslogs-stream-prefix = "seed"
        }
      }
    }
  ])

  tags = local.tags
}

# --- Scheduled: pg_dump to S3 --------------------------------------------------------------------------------------------

resource "aws_ecs_task_definition" "pg_dump" {
  count = var.enable_pg_dump ? 1 : 0

  family                   = "${var.name_prefix}-pg-dump"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 512
  memory                   = 2048
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = var.cpu_architecture
  }

  ephemeral_storage {
    size_in_gib = 50
  }

  container_definitions = jsonencode([
    {
      name      = "pg-dump"
      image     = local.api_image
      essential = true
      command   = ["/bin/sh", "-c", local.pg_dump_script]
      environment = concat(local.environment, [
        { name = "BACKUP_BUCKET", value = var.backups_bucket_name },
        { name = "BACKUP_KMS_KEY_ARN", value = var.s3_kms_key_arn },
        { name = "PGSSLMODE", value = "require" },
      ])
      secrets = [
        { name = "PGHOST", valueFrom = "${var.database_secret_arn}:host::" },
        { name = "PGPORT", valueFrom = "${var.database_secret_arn}:port::" },
        { name = "PGDATABASE", valueFrom = "${var.database_secret_arn}:dbname::" },
        { name = "PGUSER", valueFrom = "${var.database_secret_arn}:username::" },
        { name = "PGPASSWORD", valueFrom = "${var.database_secret_arn}:password::" },
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.ops["pg-dump"].name
          awslogs-region        = local.region
          awslogs-stream-prefix = "pg-dump"
        }
      }
    }
  ])

  tags = local.tags
}

data "aws_iam_policy_document" "events_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["events.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "events_run_task" {
  count = var.enable_pg_dump ? 1 : 0

  statement {
    actions   = ["ecs:RunTask"]
    resources = [aws_ecs_task_definition.pg_dump[0].arn_without_revision, aws_ecs_task_definition.pg_dump[0].arn]
    condition {
      test     = "ArnEquals"
      variable = "ecs:cluster"
      values   = [aws_ecs_cluster.this.arn]
    }
  }

  statement {
    actions   = ["iam:PassRole"]
    resources = [aws_iam_role.execution.arn, aws_iam_role.task.arn]
    condition {
      test     = "StringLike"
      variable = "iam:PassedToService"
      values   = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "events" {
  count = var.enable_pg_dump ? 1 : 0

  name               = "${var.name_prefix}-events-run-task"
  assume_role_policy = data.aws_iam_policy_document.events_assume.json
  tags               = local.tags
}

resource "aws_iam_role_policy" "events" {
  count = var.enable_pg_dump ? 1 : 0

  name   = "run-pg-dump"
  role   = aws_iam_role.events[0].id
  policy = data.aws_iam_policy_document.events_run_task[0].json
}

resource "aws_cloudwatch_event_rule" "pg_dump" {
  count = var.enable_pg_dump ? 1 : 0

  name                = "${var.name_prefix}-pg-dump"
  description         = "Daily logical PostgreSQL backup to S3"
  schedule_expression = var.pg_dump_schedule
  tags                = local.tags
}

resource "aws_cloudwatch_event_target" "pg_dump" {
  count = var.enable_pg_dump ? 1 : 0

  rule     = aws_cloudwatch_event_rule.pg_dump[0].name
  arn      = aws_ecs_cluster.this.arn
  role_arn = aws_iam_role.events[0].arn

  ecs_target {
    task_definition_arn = aws_ecs_task_definition.pg_dump[0].arn
    task_count          = 1
    launch_type         = "FARGATE"
    platform_version    = "LATEST"
    propagate_tags      = "TASK_DEFINITION"

    network_configuration {
      subnets          = var.private_subnet_ids
      security_groups  = [aws_security_group.tasks.id]
      assign_public_ip = false
    }
  }

  retry_policy {
    maximum_retry_attempts       = 2
    maximum_event_age_in_seconds = 3600
  }
}
