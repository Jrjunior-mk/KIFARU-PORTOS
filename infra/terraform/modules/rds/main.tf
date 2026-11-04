# ---------------------------------------------------------------------------------------------------------------------
# rds: PostgreSQL 16 on RDS.
#   * KMS-encrypted storage (customer-managed key), TLS enforced (rds.force_ssl = 1)
#   * Multi-AZ (prod), gp3, storage autoscaling
#   * 35-day automated backups with PITR; optional cross-region automated-backup replication to the DR region
#   * Credentials in Secrets Manager with an optional rotation hook (owner supplies the rotation Lambda ARN)
#   * Two secrets: <prefix>/database (JSON parts; used by pg_dump and rotation) and <prefix>/database-url (SQLAlchemy URL)
# ---------------------------------------------------------------------------------------------------------------------

locals {
  tags = merge(var.tags, { DataClass = "Confidential-PII" })
  port = 5432
}

# --- KMS (primary + DR) ------------------------------------------------------------------------------------------------

resource "aws_kms_key" "rds" {
  description             = "${var.name_prefix} RDS storage encryption"
  deletion_window_in_days = 30
  enable_key_rotation     = true
  tags                    = local.tags
}

resource "aws_kms_alias" "rds" {
  name          = "alias/${var.name_prefix}-rds"
  target_key_id = aws_kms_key.rds.key_id
}

resource "aws_kms_key" "rds_dr" {
  count    = var.enable_cross_region_backup_replication ? 1 : 0
  provider = aws.dr

  description             = "${var.name_prefix} RDS replicated backups (DR region)"
  deletion_window_in_days = 30
  enable_key_rotation     = true
  tags                    = local.tags
}

# --- Networking --------------------------------------------------------------------------------------------------------

resource "aws_db_subnet_group" "this" {
  name       = "${var.name_prefix}-db"
  subnet_ids = var.subnet_ids
  tags       = merge(local.tags, { Name = "${var.name_prefix}-db" })
}

resource "aws_security_group" "this" {
  name        = "${var.name_prefix}-rds"
  description = "PostgreSQL access from application tasks only"
  vpc_id      = var.vpc_id
  tags        = merge(local.tags, { Name = "${var.name_prefix}-rds" })
}

resource "aws_vpc_security_group_ingress_rule" "from_apps" {
  for_each = toset(var.allowed_security_group_ids)

  security_group_id            = aws_security_group.this.id
  description                  = "PostgreSQL from application security group"
  from_port                    = local.port
  to_port                      = local.port
  ip_protocol                  = "tcp"
  referenced_security_group_id = each.value
}

# --- Parameter group ---------------------------------------------------------------------------------------------------

resource "aws_db_parameter_group" "this" {
  name        = "${var.name_prefix}-postgres16"
  family      = "postgres16"
  description = "KIFARU PORTOS PostgreSQL 16 parameters"

  parameter {
    name  = "rds.force_ssl"
    value = "1"
  }

  parameter {
    name  = "log_min_duration_statement"
    value = "1000"
  }

  parameter {
    name  = "log_connections"
    value = "1"
  }

  parameter {
    name         = "shared_preload_libraries"
    value        = "pg_stat_statements"
    apply_method = "pending-reboot"
  }

  parameter {
    name  = "pg_stat_statements.track"
    value = "all"
  }

  parameter {
    name  = "timezone"
    value = "UTC"
  }

  tags = local.tags

  lifecycle {
    create_before_destroy = true
  }
}

# --- Enhanced monitoring role ------------------------------------------------------------------------------------------

data "aws_iam_policy_document" "monitoring_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["monitoring.rds.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "monitoring" {
  count = var.enhanced_monitoring_interval > 0 ? 1 : 0

  name               = "${var.name_prefix}-rds-monitoring"
  assume_role_policy = data.aws_iam_policy_document.monitoring_assume.json
  tags               = local.tags
}

resource "aws_iam_role_policy_attachment" "monitoring" {
  count = var.enhanced_monitoring_interval > 0 ? 1 : 0

  role       = aws_iam_role.monitoring[0].name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonRDSEnhancedMonitoringRole"
}

# --- Credentials -------------------------------------------------------------------------------------------------------

resource "random_password" "master" {
  length           = 32
  special          = true
  override_special = "!#$%^&*()-_=+[]{}<>:?" # excludes / @ " and space, which break URLs and RDS
}

# --- Instance ----------------------------------------------------------------------------------------------------------

resource "aws_db_instance" "this" {
  identifier = "${var.name_prefix}-postgres"

  engine                = "postgres"
  engine_version        = var.engine_version
  instance_class        = var.instance_class
  allocated_storage     = var.allocated_storage
  max_allocated_storage = var.max_allocated_storage > 0 ? var.max_allocated_storage : null
  storage_type          = "gp3"
  storage_encrypted     = true
  kms_key_id            = aws_kms_key.rds.arn

  db_name  = var.db_name
  username = var.master_username
  password = random_password.master.result
  port     = local.port

  multi_az               = var.multi_az
  db_subnet_group_name   = aws_db_subnet_group.this.name
  vpc_security_group_ids = [aws_security_group.this.id]
  publicly_accessible    = false
  parameter_group_name   = aws_db_parameter_group.this.name
  ca_cert_identifier     = "rds-ca-rsa2048-g1"

  backup_retention_period   = var.backup_retention_period
  backup_window             = var.backup_window
  maintenance_window        = var.maintenance_window
  copy_tags_to_snapshot     = true
  delete_automated_backups  = false
  deletion_protection       = var.deletion_protection
  skip_final_snapshot       = var.skip_final_snapshot
  final_snapshot_identifier = var.skip_final_snapshot ? null : "${var.name_prefix}-postgres-final"

  auto_minor_version_upgrade  = true
  allow_major_version_upgrade = false
  apply_immediately           = false

  performance_insights_enabled          = var.performance_insights_enabled
  performance_insights_kms_key_id       = var.performance_insights_enabled ? aws_kms_key.rds.arn : null
  performance_insights_retention_period = var.performance_insights_enabled ? 7 : null
  monitoring_interval                   = var.enhanced_monitoring_interval
  monitoring_role_arn                   = var.enhanced_monitoring_interval > 0 ? aws_iam_role.monitoring[0].arn : null
  enabled_cloudwatch_logs_exports       = ["postgresql", "upgrade"]

  tags = merge(local.tags, { Name = "${var.name_prefix}-postgres" })

  lifecycle {
    ignore_changes = [engine_version] # minor upgrades are applied by RDS in the maintenance window
  }
}

# Cross-region automated backup replication (snapshots + transaction logs) -> DR region.
resource "aws_db_instance_automated_backups_replication" "dr" {
  count    = var.enable_cross_region_backup_replication ? 1 : 0
  provider = aws.dr

  source_db_instance_arn = aws_db_instance.this.arn
  kms_key_id             = aws_kms_key.rds_dr[0].arn
  retention_period       = var.dr_backup_retention_period
}

# --- Secrets -----------------------------------------------------------------------------------------------------------

resource "aws_secretsmanager_secret" "database" {
  name                    = "${var.secret_path_prefix}/database"
  description             = "RDS master credentials as JSON (Secrets Manager rotation format)"
  kms_key_id              = var.secrets_kms_key_arn
  recovery_window_in_days = var.recovery_window_in_days
  tags                    = local.tags
}

resource "aws_secretsmanager_secret_version" "database" {
  secret_id = aws_secretsmanager_secret.database.id
  secret_string = jsonencode({
    engine               = "postgres"
    host                 = aws_db_instance.this.address
    port                 = local.port
    dbname               = var.db_name
    username             = var.master_username
    password             = random_password.master.result
    dbInstanceIdentifier = aws_db_instance.this.identifier
  })

  lifecycle {
    ignore_changes = [secret_string] # a rotation Lambda owns the value after the first write
  }
}

resource "aws_secretsmanager_secret" "database_url" {
  name                    = "${var.secret_path_prefix}/database-url"
  description             = "SQLAlchemy URL injected as KIFARU_DATABASE_URL"
  kms_key_id              = var.secrets_kms_key_arn
  recovery_window_in_days = var.recovery_window_in_days
  tags                    = local.tags
}

resource "aws_secretsmanager_secret_version" "database_url" {
  secret_id     = aws_secretsmanager_secret.database_url.id
  secret_string = "postgresql+psycopg://${var.master_username}:${urlencode(random_password.master.result)}@${aws_db_instance.this.address}:${local.port}/${var.db_name}?sslmode=require"

  lifecycle {
    ignore_changes = [secret_string]
  }
}

resource "aws_secretsmanager_secret_rotation" "database" {
  count = var.rotation_lambda_arn == null ? 0 : 1

  secret_id           = aws_secretsmanager_secret.database.id
  rotation_lambda_arn = var.rotation_lambda_arn

  rotation_rules {
    automatically_after_days = var.rotation_days
  }
}
