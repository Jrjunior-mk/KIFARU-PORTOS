# ---------------------------------------------------------------------------------------------------------------------
# queue: two SQS queues.
#   events  - station events routed by the IoT Core topic rule (kifaru/stations/+/events) and consumed by `ingest`
#   jobs    - background jobs (forecasting, passport updates, notifications) consumed by `worker`
# Each has its own dead-letter queue; DLQ depth is alarmed in the monitoring module.
# ---------------------------------------------------------------------------------------------------------------------

locals {
  tags   = merge(var.tags, { DataClass = "Confidential" })
  queues = toset(["events", "jobs"])
}

resource "aws_sqs_queue" "dlq" {
  for_each = local.queues

  name                      = "${var.name_prefix}-${each.key}-dlq"
  message_retention_seconds = var.dlq_retention_seconds
  sqs_managed_sse_enabled   = var.kms_key_arn == null ? true : null
  kms_master_key_id         = var.kms_key_arn

  tags = merge(local.tags, { Name = "${var.name_prefix}-${each.key}-dlq" })
}

resource "aws_sqs_queue" "main" {
  for_each = local.queues

  name                       = "${var.name_prefix}-${each.key}"
  visibility_timeout_seconds = var.visibility_timeout_seconds
  message_retention_seconds  = var.message_retention_seconds
  receive_wait_time_seconds  = 20
  sqs_managed_sse_enabled    = var.kms_key_arn == null ? true : null
  kms_master_key_id          = var.kms_key_arn

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq[each.key].arn
    maxReceiveCount     = var.max_receive_count
  })

  tags = merge(local.tags, { Name = "${var.name_prefix}-${each.key}" })
}

resource "aws_sqs_queue_redrive_allow_policy" "dlq" {
  for_each = local.queues

  queue_url = aws_sqs_queue.dlq[each.key].id

  redrive_allow_policy = jsonencode({
    redrivePermission = "byQueue"
    sourceQueueArns   = [aws_sqs_queue.main[each.key].arn]
  })
}

# Deny unencrypted transport on all queues.
data "aws_iam_policy_document" "tls_only" {
  for_each = local.queues

  statement {
    sid     = "DenyInsecureTransport"
    effect  = "Deny"
    actions = ["sqs:*"]
    principals {
      type        = "AWS"
      identifiers = ["*"]
    }
    resources = [aws_sqs_queue.main[each.key].arn]
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_sqs_queue_policy" "tls_only" {
  for_each = local.queues

  queue_url = aws_sqs_queue.main[each.key].id
  policy    = data.aws_iam_policy_document.tls_only[each.key].json
}
