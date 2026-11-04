# ---------------------------------------------------------------------------------------------------------------------
# redis: ElastiCache for Redis 7 replication group with in-transit TLS, at-rest encryption and AUTH token.
# Used for WebSocket fan-out (channel kifaru.events), rate limiting and idempotency keys. The URL is stored in
# Secrets Manager and injected as KIFARU_REDIS_URL (rediss://).
# ---------------------------------------------------------------------------------------------------------------------

locals {
  tags = merge(var.tags, { DataClass = "Internal" })
  port = 6379
  ha   = var.num_cache_clusters > 1
}

resource "aws_elasticache_subnet_group" "this" {
  name       = "${var.name_prefix}-redis"
  subnet_ids = var.subnet_ids
  tags       = local.tags
}

resource "aws_security_group" "this" {
  name        = "${var.name_prefix}-redis"
  description = "Redis access from application tasks only"
  vpc_id      = var.vpc_id
  tags        = merge(local.tags, { Name = "${var.name_prefix}-redis" })
}

resource "aws_vpc_security_group_ingress_rule" "from_apps" {
  for_each = toset(var.allowed_security_group_ids)

  security_group_id            = aws_security_group.this.id
  description                  = "Redis from application security group"
  from_port                    = local.port
  to_port                      = local.port
  ip_protocol                  = "tcp"
  referenced_security_group_id = each.value
}

resource "aws_elasticache_parameter_group" "this" {
  name        = "${var.name_prefix}-redis7"
  family      = "redis7"
  description = "KIFARU PORTOS Redis 7 parameters"

  parameter {
    name  = "maxmemory-policy"
    value = "volatile-lru"
  }

  parameter {
    name  = "notify-keyspace-events"
    value = "Ex"
  }

  tags = local.tags

  lifecycle {
    create_before_destroy = true
  }
}

# AUTH token: 16-128 printable chars excluding @ " /
resource "random_password" "auth" {
  length           = 48
  special          = true
  override_special = "!#$%^&*()-_=+"
}

resource "aws_elasticache_replication_group" "this" {
  replication_group_id = "${var.name_prefix}-redis"
  description          = "KIFARU PORTOS ${var.name_prefix} Redis"

  engine               = "redis"
  engine_version       = var.engine_version
  node_type            = var.node_type
  port                 = local.port
  parameter_group_name = aws_elasticache_parameter_group.this.name
  subnet_group_name    = aws_elasticache_subnet_group.this.name
  security_group_ids   = [aws_security_group.this.id]

  num_cache_clusters         = var.num_cache_clusters
  automatic_failover_enabled = local.ha
  multi_az_enabled           = local.ha

  at_rest_encryption_enabled = true
  transit_encryption_enabled = true
  auth_token                 = random_password.auth.result
  auth_token_update_strategy = "ROTATE"

  snapshot_retention_limit   = var.snapshot_retention_limit
  snapshot_window            = var.snapshot_window
  maintenance_window         = var.maintenance_window
  auto_minor_version_upgrade = true
  apply_immediately          = false

  tags = merge(local.tags, { Name = "${var.name_prefix}-redis" })
}

# --- Secrets -----------------------------------------------------------------------------------------------------------

resource "aws_secretsmanager_secret" "redis_url" {
  name                    = "${var.secret_path_prefix}/redis-url"
  description             = "Redis URL with AUTH token, injected as KIFARU_REDIS_URL"
  kms_key_id              = var.secrets_kms_key_arn
  recovery_window_in_days = var.recovery_window_in_days
  tags                    = merge(local.tags, { DataClass = "Secret" })
}

resource "aws_secretsmanager_secret_version" "redis_url" {
  secret_id     = aws_secretsmanager_secret.redis_url.id
  secret_string = "rediss://:${urlencode(random_password.auth.result)}@${aws_elasticache_replication_group.this.primary_endpoint_address}:${local.port}/0"
}
