output "sns_topic_arn" {
  description = "Alarm SNS topic ARN (subscribe PagerDuty/Slack/SMS here)."
  value       = aws_sns_topic.alarms.arn
}

output "dashboard_name" {
  description = "CloudWatch dashboard name."
  value       = aws_cloudwatch_dashboard.ops.dashboard_name
}

output "alarm_names" {
  description = "All alarm names created by the module."
  value = concat(
    [
      aws_cloudwatch_metric_alarm.alb_5xx.alarm_name,
      aws_cloudwatch_metric_alarm.target_5xx.alarm_name,
      aws_cloudwatch_metric_alarm.latency_p99.alarm_name,
      aws_cloudwatch_metric_alarm.rds_cpu.alarm_name,
      aws_cloudwatch_metric_alarm.rds_storage.alarm_name,
      aws_cloudwatch_metric_alarm.rds_connections.alarm_name,
      aws_cloudwatch_metric_alarm.redis_cpu.alarm_name,
      aws_cloudwatch_metric_alarm.redis_memory.alarm_name,
      aws_cloudwatch_metric_alarm.events_queue_age.alarm_name,
    ],
    [for a in aws_cloudwatch_metric_alarm.unhealthy_targets : a.alarm_name],
    [for a in aws_cloudwatch_metric_alarm.ecs_cpu : a.alarm_name],
    [for a in aws_cloudwatch_metric_alarm.ecs_memory : a.alarm_name],
    [for a in aws_cloudwatch_metric_alarm.dlq_depth : a.alarm_name],
  )
}
