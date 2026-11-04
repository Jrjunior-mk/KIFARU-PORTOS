output "events_queue_arn" {
  description = "ARN of the station-events queue (IoT rule target)."
  value       = aws_sqs_queue.main["events"].arn
}

output "events_queue_url" {
  description = "URL of the station-events queue (KIFARU_EVENTS_QUEUE_URL for the ingest service)."
  value       = aws_sqs_queue.main["events"].id
}

output "events_queue_name" {
  description = "Name of the station-events queue."
  value       = aws_sqs_queue.main["events"].name
}

output "jobs_queue_arn" {
  description = "ARN of the background-jobs queue."
  value       = aws_sqs_queue.main["jobs"].arn
}

output "jobs_queue_url" {
  description = "URL of the background-jobs queue (KIFARU_JOBS_QUEUE_URL for api/worker)."
  value       = aws_sqs_queue.main["jobs"].id
}

output "jobs_queue_name" {
  description = "Name of the background-jobs queue."
  value       = aws_sqs_queue.main["jobs"].name
}

output "dlq_names" {
  description = "Map queue key => DLQ name (for alarms)."
  value       = { for k, q in aws_sqs_queue.dlq : k => q.name }
}

output "dlq_arns" {
  description = "Map queue key => DLQ ARN."
  value       = { for k, q in aws_sqs_queue.dlq : k => q.arn }
}

output "all_queue_arns" {
  description = "All queue ARNs (main + DLQ) for IAM policies."
  value       = concat([for q in aws_sqs_queue.main : q.arn], [for q in aws_sqs_queue.dlq : q.arn])
}
