# ---------------------------------------------------------------------------------------------------------------------
# monitoring: SNS alarm topic (+ e-mail subscription), CloudWatch alarms and an operations dashboard.
# Alarms: ALB 5xx, unhealthy targets, p99 latency, RDS CPU/storage/connections, ECS CPU/memory per service,
#         Redis CPU/memory, SQS DLQ depth, events queue age.
# ---------------------------------------------------------------------------------------------------------------------

data "aws_region" "current" {}

locals {
  tags   = merge(var.tags, { DataClass = "Internal" })
  region = data.aws_region.current.name
  topic  = [aws_sns_topic.alarms.arn]
}

# --- SNS ---------------------------------------------------------------------------------------------------------------

resource "aws_sns_topic" "alarms" {
  name              = "${var.name_prefix}-alarms"
  kms_master_key_id = "alias/aws/sns"
  tags              = local.tags
}

data "aws_iam_policy_document" "sns" {
  statement {
    sid     = "AllowCloudWatchAlarms"
    actions = ["sns:Publish"]
    principals {
      type        = "Service"
      identifiers = ["cloudwatch.amazonaws.com"]
    }
    resources = [aws_sns_topic.alarms.arn]
  }
}

resource "aws_sns_topic_policy" "alarms" {
  arn    = aws_sns_topic.alarms.arn
  policy = data.aws_iam_policy_document.sns.json
}

resource "aws_sns_topic_subscription" "email" {
  count = var.alarm_email == "" ? 0 : 1

  topic_arn = aws_sns_topic.alarms.arn
  protocol  = "email"
  endpoint  = var.alarm_email
}

# --- ALB ---------------------------------------------------------------------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "alb_5xx" {
  alarm_name          = "${var.name_prefix}-alb-5xx"
  alarm_description   = "ALB returned >= ${var.alb_5xx_threshold} 5xx responses in 5 minutes (ELB-generated)"
  namespace           = "AWS/ApplicationELB"
  metric_name         = "HTTPCode_ELB_5XX_Count"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = var.alb_5xx_threshold
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  dimensions          = { LoadBalancer = var.alb_arn_suffix }
  alarm_actions       = local.topic
  ok_actions          = local.topic
  tags                = local.tags
}

resource "aws_cloudwatch_metric_alarm" "target_5xx" {
  alarm_name          = "${var.name_prefix}-target-5xx"
  alarm_description   = "Application returned >= ${var.alb_5xx_threshold} 5xx responses in 5 minutes"
  namespace           = "AWS/ApplicationELB"
  metric_name         = "HTTPCode_Target_5XX_Count"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = var.alb_5xx_threshold
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  dimensions          = { LoadBalancer = var.alb_arn_suffix }
  alarm_actions       = local.topic
  ok_actions          = local.topic
  tags                = local.tags
}

resource "aws_cloudwatch_metric_alarm" "unhealthy_targets" {
  for_each = var.target_group_arn_suffixes

  alarm_name          = "${var.name_prefix}-${each.key}-unhealthy-targets"
  alarm_description   = "Target group ${each.key} has unhealthy targets"
  namespace           = "AWS/ApplicationELB"
  metric_name         = "UnHealthyHostCount"
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 3
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  dimensions = {
    LoadBalancer = var.alb_arn_suffix
    TargetGroup  = each.value
  }
  alarm_actions = local.topic
  ok_actions    = local.topic
  tags          = local.tags
}

resource "aws_cloudwatch_metric_alarm" "latency_p99" {
  alarm_name          = "${var.name_prefix}-api-latency-p99"
  alarm_description   = "p99 target response time above ${var.api_latency_p99_threshold_seconds}s for 10 minutes"
  namespace           = "AWS/ApplicationELB"
  metric_name         = "TargetResponseTime"
  extended_statistic  = "p99"
  period              = 300
  evaluation_periods  = 2
  threshold           = var.api_latency_p99_threshold_seconds
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  dimensions          = { LoadBalancer = var.alb_arn_suffix }
  alarm_actions       = local.topic
  ok_actions          = local.topic
  tags                = local.tags
}

# --- RDS ---------------------------------------------------------------------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "rds_cpu" {
  alarm_name          = "${var.name_prefix}-rds-cpu"
  alarm_description   = "RDS CPU above 80 % for 15 minutes"
  namespace           = "AWS/RDS"
  metric_name         = "CPUUtilization"
  statistic           = "Average"
  period              = 300
  evaluation_periods  = 3
  threshold           = 80
  comparison_operator = "GreaterThanThreshold"
  dimensions          = { DBInstanceIdentifier = var.rds_instance_identifier }
  alarm_actions       = local.topic
  ok_actions          = local.topic
  tags                = local.tags
}

resource "aws_cloudwatch_metric_alarm" "rds_storage" {
  alarm_name          = "${var.name_prefix}-rds-free-storage"
  alarm_description   = "RDS free storage below threshold"
  namespace           = "AWS/RDS"
  metric_name         = "FreeStorageSpace"
  statistic           = "Minimum"
  period              = 300
  evaluation_periods  = 1
  threshold           = var.rds_free_storage_threshold_bytes
  comparison_operator = "LessThanThreshold"
  dimensions          = { DBInstanceIdentifier = var.rds_instance_identifier }
  alarm_actions       = local.topic
  ok_actions          = local.topic
  tags                = local.tags
}

resource "aws_cloudwatch_metric_alarm" "rds_connections" {
  alarm_name          = "${var.name_prefix}-rds-connections"
  alarm_description   = "RDS connection count above ${var.rds_max_connections}"
  namespace           = "AWS/RDS"
  metric_name         = "DatabaseConnections"
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 2
  threshold           = var.rds_max_connections
  comparison_operator = "GreaterThanThreshold"
  dimensions          = { DBInstanceIdentifier = var.rds_instance_identifier }
  alarm_actions       = local.topic
  ok_actions          = local.topic
  tags                = local.tags
}

# --- ECS ---------------------------------------------------------------------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "ecs_cpu" {
  for_each = var.ecs_service_names

  alarm_name          = "${var.name_prefix}-${each.key}-cpu"
  alarm_description   = "ECS service ${each.key} CPU above 85 % for 15 minutes (autoscaling ceiling reached?)"
  namespace           = "AWS/ECS"
  metric_name         = "CPUUtilization"
  statistic           = "Average"
  period              = 300
  evaluation_periods  = 3
  threshold           = 85
  comparison_operator = "GreaterThanThreshold"
  dimensions = {
    ClusterName = var.ecs_cluster_name
    ServiceName = each.value
  }
  alarm_actions = local.topic
  ok_actions    = local.topic
  tags          = local.tags
}

resource "aws_cloudwatch_metric_alarm" "ecs_memory" {
  for_each = var.ecs_service_names

  alarm_name          = "${var.name_prefix}-${each.key}-memory"
  alarm_description   = "ECS service ${each.key} memory above 85 % for 15 minutes"
  namespace           = "AWS/ECS"
  metric_name         = "MemoryUtilization"
  statistic           = "Average"
  period              = 300
  evaluation_periods  = 3
  threshold           = 85
  comparison_operator = "GreaterThanThreshold"
  dimensions = {
    ClusterName = var.ecs_cluster_name
    ServiceName = each.value
  }
  alarm_actions = local.topic
  ok_actions    = local.topic
  tags          = local.tags
}

# --- Redis -------------------------------------------------------------------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "redis_cpu" {
  alarm_name          = "${var.name_prefix}-redis-cpu"
  alarm_description   = "Redis engine CPU above 80 %"
  namespace           = "AWS/ElastiCache"
  metric_name         = "EngineCPUUtilization"
  statistic           = "Average"
  period              = 300
  evaluation_periods  = 3
  threshold           = 80
  comparison_operator = "GreaterThanThreshold"
  dimensions          = { ReplicationGroupId = var.redis_replication_group_id }
  alarm_actions       = local.topic
  ok_actions          = local.topic
  tags                = local.tags
}

resource "aws_cloudwatch_metric_alarm" "redis_memory" {
  alarm_name          = "${var.name_prefix}-redis-memory"
  alarm_description   = "Redis memory usage above 80 %"
  namespace           = "AWS/ElastiCache"
  metric_name         = "DatabaseMemoryUsagePercentage"
  statistic           = "Average"
  period              = 300
  evaluation_periods  = 3
  threshold           = 80
  comparison_operator = "GreaterThanThreshold"
  dimensions          = { ReplicationGroupId = var.redis_replication_group_id }
  alarm_actions       = local.topic
  ok_actions          = local.topic
  tags                = local.tags
}

# --- SQS ---------------------------------------------------------------------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "dlq_depth" {
  for_each = var.dlq_names

  alarm_name          = "${var.name_prefix}-${each.key}-dlq-depth"
  alarm_description   = "Messages in the ${each.key} dead-letter queue need operator attention"
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  dimensions          = { QueueName = each.value }
  alarm_actions       = local.topic
  ok_actions          = local.topic
  tags                = local.tags
}

resource "aws_cloudwatch_metric_alarm" "events_queue_age" {
  alarm_name          = "${var.name_prefix}-events-queue-age"
  alarm_description   = "Oldest station event has waited more than 5 minutes (ingest stalled?)"
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateAgeOfOldestMessage"
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 300
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  dimensions          = { QueueName = var.events_queue_name }
  alarm_actions       = local.topic
  ok_actions          = local.topic
  tags                = local.tags
}

# --- Dashboard ---------------------------------------------------------------------------------------------------------

resource "aws_cloudwatch_dashboard" "ops" {
  dashboard_name = "${var.name_prefix}-ops"

  dashboard_body = jsonencode({
    widgets = [
      {
        type   = "metric"
        x      = 0
        y      = 0
        width  = 12
        height = 6
        properties = {
          title  = "ALB requests and 5xx"
          region = local.region
          stat   = "Sum"
          period = 60
          metrics = [
            ["AWS/ApplicationELB", "RequestCount", "LoadBalancer", var.alb_arn_suffix],
            ["AWS/ApplicationELB", "HTTPCode_Target_5XX_Count", "LoadBalancer", var.alb_arn_suffix],
            ["AWS/ApplicationELB", "HTTPCode_ELB_5XX_Count", "LoadBalancer", var.alb_arn_suffix],
          ]
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 0
        width  = 12
        height = 6
        properties = {
          title  = "API latency (p50 / p99)"
          region = local.region
          period = 60
          metrics = [
            ["AWS/ApplicationELB", "TargetResponseTime", "LoadBalancer", var.alb_arn_suffix, { stat = "p50" }],
            ["AWS/ApplicationELB", "TargetResponseTime", "LoadBalancer", var.alb_arn_suffix, { stat = "p99" }],
          ]
        }
      },
      {
        type   = "metric"
        x      = 0
        y      = 6
        width  = 12
        height = 6
        properties = {
          title  = "ECS CPU per service"
          region = local.region
          stat   = "Average"
          period = 60
          metrics = [
            for k, name in var.ecs_service_names : ["AWS/ECS", "CPUUtilization", "ClusterName", var.ecs_cluster_name, "ServiceName", name]
          ]
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 6
        width  = 12
        height = 6
        properties = {
          title  = "ECS memory per service"
          region = local.region
          stat   = "Average"
          period = 60
          metrics = [
            for k, name in var.ecs_service_names : ["AWS/ECS", "MemoryUtilization", "ClusterName", var.ecs_cluster_name, "ServiceName", name]
          ]
        }
      },
      {
        type   = "metric"
        x      = 0
        y      = 12
        width  = 8
        height = 6
        properties = {
          title  = "RDS CPU / connections"
          region = local.region
          period = 60
          metrics = [
            ["AWS/RDS", "CPUUtilization", "DBInstanceIdentifier", var.rds_instance_identifier, { stat = "Average" }],
            ["AWS/RDS", "DatabaseConnections", "DBInstanceIdentifier", var.rds_instance_identifier, { stat = "Maximum", yAxis = "right" }],
          ]
        }
      },
      {
        type   = "metric"
        x      = 8
        y      = 12
        width  = 8
        height = 6
        properties = {
          title  = "RDS free storage (bytes)"
          region = local.region
          stat   = "Minimum"
          period = 300
          metrics = [
            ["AWS/RDS", "FreeStorageSpace", "DBInstanceIdentifier", var.rds_instance_identifier],
          ]
        }
      },
      {
        type   = "metric"
        x      = 16
        y      = 12
        width  = 8
        height = 6
        properties = {
          title  = "Redis CPU / memory %"
          region = local.region
          stat   = "Average"
          period = 60
          metrics = [
            ["AWS/ElastiCache", "EngineCPUUtilization", "ReplicationGroupId", var.redis_replication_group_id],
            ["AWS/ElastiCache", "DatabaseMemoryUsagePercentage", "ReplicationGroupId", var.redis_replication_group_id],
          ]
        }
      },
      {
        type   = "metric"
        x      = 0
        y      = 18
        width  = 12
        height = 6
        properties = {
          title  = "Station events queue"
          region = local.region
          period = 60
          metrics = [
            ["AWS/SQS", "NumberOfMessagesReceived", "QueueName", var.events_queue_name, { stat = "Sum" }],
            ["AWS/SQS", "ApproximateAgeOfOldestMessage", "QueueName", var.events_queue_name, { stat = "Maximum", yAxis = "right" }],
          ]
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 18
        width  = 12
        height = 6
        properties = {
          title  = "Dead-letter queue depth"
          region = local.region
          stat   = "Maximum"
          period = 60
          metrics = [
            for k, name in var.dlq_names : ["AWS/SQS", "ApproximateNumberOfMessagesVisible", "QueueName", name]
          ]
        }
      },
    ]
  })
}
