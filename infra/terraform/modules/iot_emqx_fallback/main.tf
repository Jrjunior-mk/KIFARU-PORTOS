# ---------------------------------------------------------------------------------------------------------------------
# iot_emqx_fallback: self-hosted EMQX 5 on ECS Fargate behind a Network Load Balancer.
#
# Used only when AWS IoT Core is not available (or not approved) in af-south-1. Selected in the environment root with
# `iot_mode = "emqx"`. This is a deliberately minimal single-node deployment: EMQX's built-in authentication (per-device
# username/password or X.509 via its `listeners.ssl.default.ssl_options.verify = verify_peer`) replaces IoT Core policies,
# and the `ingest` service subscribes directly to kifaru/stations/+/events over MQTT instead of consuming SQS.
#
# Known limitations (documented, accepted for a fallback):
#   * no persistent session store (tasks are ephemeral); gateways re-send from their SQLite outbox on reconnect
#   * single task; scale-out requires EMQX clustering with a discovery strategy (DNS) and is out of scope here
#   * per-device credentials are managed in EMQX, not IAM; see README.md in this folder
# ---------------------------------------------------------------------------------------------------------------------

data "aws_region" "current" {}

locals {
  tags = merge(var.tags, { DataClass = "Confidential" })
}

resource "aws_cloudwatch_log_group" "emqx" {
  name              = "/kifaru/${var.name_prefix}/emqx"
  retention_in_days = var.log_retention_days
  tags              = local.tags
}

resource "aws_security_group" "emqx" {
  name        = "${var.name_prefix}-emqx"
  description = "EMQX broker tasks"
  vpc_id      = var.vpc_id
  tags        = merge(local.tags, { Name = "${var.name_prefix}-emqx" })
}

resource "aws_vpc_security_group_ingress_rule" "mqtt_tls" {
  for_each = toset(var.allowed_cidrs)

  security_group_id = aws_security_group.emqx.id
  description       = "MQTT over TLS from NLB (preserved client IP)"
  from_port         = 8883
  to_port           = 8883
  ip_protocol       = "tcp"
  cidr_ipv4         = each.value
}

resource "aws_vpc_security_group_ingress_rule" "dashboard" {
  for_each = toset(var.dashboard_cidrs)

  security_group_id = aws_security_group.emqx.id
  description       = "EMQX dashboard"
  from_port         = 18083
  to_port           = 18083
  ip_protocol       = "tcp"
  cidr_ipv4         = each.value
}

resource "aws_vpc_security_group_egress_rule" "all" {
  security_group_id = aws_security_group.emqx.id
  description       = "All egress"
  ip_protocol       = "-1"
  cidr_ipv4         = "0.0.0.0/0"
}

# --- NLB ---------------------------------------------------------------------------------------------------------------

resource "aws_lb" "emqx" {
  name                             = "${var.name_prefix}-emqx"
  load_balancer_type               = "network"
  internal                         = false
  subnets                          = var.public_subnet_ids
  enable_cross_zone_load_balancing = true
  tags                             = merge(local.tags, { Name = "${var.name_prefix}-emqx" })
}

resource "aws_lb_target_group" "mqtt" {
  name        = "${var.name_prefix}-emqx-mqtt"
  port        = 1883
  protocol    = "TCP"
  target_type = "ip"
  vpc_id      = var.vpc_id

  health_check {
    protocol = "TCP"
    port     = "1883"
  }

  tags = local.tags
}

# TLS is terminated at the NLB (ACM certificate); the NLB forwards plain MQTT to the task inside the VPC.
# For true end-to-end mTLS switch the listener to TCP passthrough on 8883 and enable verify_peer in EMQX.
resource "aws_lb_listener" "mqtt_tls" {
  load_balancer_arn = aws_lb.emqx.arn
  port              = 8883
  protocol          = "TLS"
  certificate_arn   = var.certificate_arn
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.mqtt.arn
  }

  tags = local.tags
}

# --- ECS ---------------------------------------------------------------------------------------------------------------

resource "aws_ecs_task_definition" "emqx" {
  family                   = "${var.name_prefix}-emqx"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.cpu
  memory                   = var.memory
  execution_role_arn       = var.execution_role_arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  container_definitions = jsonencode([
    {
      name      = "emqx"
      image     = var.emqx_image
      essential = true
      portMappings = [
        { containerPort = 1883, protocol = "tcp" },
        { containerPort = 8883, protocol = "tcp" },
        { containerPort = 18083, protocol = "tcp" },
      ]
      environment = [
        { name = "EMQX_NODE__NAME", value = "emqx@127.0.0.1" },
        { name = "EMQX_ALLOW_ANONYMOUS", value = "false" },
        { name = "EMQX_LISTENERS__TCP__DEFAULT__BIND", value = "0.0.0.0:1883" },
        { name = "EMQX_LISTENERS__SSL__DEFAULT__BIND", value = "0.0.0.0:8883" },
        { name = "EMQX_DASHBOARD__LISTENERS__HTTP__BIND", value = "18083" },
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.emqx.name
          awslogs-region        = data.aws_region.current.name
          awslogs-stream-prefix = "emqx"
        }
      }
      healthCheck = {
        command     = ["CMD-SHELL", "emqx ctl status | grep -q 'is started' || exit 1"]
        interval    = 30
        timeout     = 5
        retries     = 3
        startPeriod = 60
      }
    }
  ])

  tags = local.tags
}

resource "aws_ecs_service" "emqx" {
  name            = "${var.name_prefix}-emqx"
  cluster         = var.cluster_arn
  task_definition = aws_ecs_task_definition.emqx.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [aws_security_group.emqx.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.mqtt.arn
    container_name   = "emqx"
    container_port   = 1883
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  tags = local.tags
}
