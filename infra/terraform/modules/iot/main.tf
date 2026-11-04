# ---------------------------------------------------------------------------------------------------------------------
# iot: AWS IoT Core for station gateways.
#   * Thing type `<prefix>-station-gateway`; one Thing per lane gateway (e.g. gw-mrk-l1), created by the onboarding
#     procedure in docs/06-operations/deployment-guide.md (certificate issued per thing, never shared).
#   * Device policy scoped with `${iot:Connection.Thing.ThingName}`: a gateway may only connect with its own client id,
#     publish to kifaru/stations/<its name>/events and subscribe to kifaru/stations/<its name>/commands.
#   * Topic rule forwards every message on kifaru/stations/+/events to the SQS events queue (ingest consumer).
#
# IoT Core availability in af-south-1 must be verified at deployment time; if unavailable, set `iot_mode = "emqx"` in the
# environment root to deploy modules/iot_emqx_fallback instead.
# ---------------------------------------------------------------------------------------------------------------------

data "aws_region" "current" {}
data "aws_caller_identity" "current" {}

data "aws_iot_endpoint" "data" {
  endpoint_type = "iot:Data-ATS"
}

locals {
  tags   = merge(var.tags, { DataClass = "Confidential" })
  region = data.aws_region.current.name
  acct   = data.aws_caller_identity.current.account_id
}

# --- Thing type --------------------------------------------------------------------------------------------------------

resource "aws_iot_thing_type" "station_gateway" {
  name = "${var.name_prefix}-station-gateway"

  properties {
    description           = "KIFARU PORTOS roadside lane gateway (edge clearance engine + WIM DAQ uplink)"
    searchable_attributes = ["station_code", "lane_no", "firmware"]
  }

  tags = local.tags
}

# --- Per-thing device policy -------------------------------------------------------------------------------------------

data "aws_iam_policy_document" "device" {
  statement {
    sid       = "ConnectAsSelf"
    actions   = ["iot:Connect"]
    resources = ["arn:aws:iot:${local.region}:${local.acct}:client/$${iot:Connection.Thing.ThingName}"]
    condition {
      test     = "Bool"
      variable = "iot:Connection.Thing.IsAttached"
      values   = ["true"]
    }
  }

  statement {
    sid       = "PublishOwnEvents"
    actions   = ["iot:Publish"]
    resources = ["arn:aws:iot:${local.region}:${local.acct}:topic/${var.topic_prefix}/$${iot:Connection.Thing.ThingName}/events"]
  }

  statement {
    sid       = "SubscribeOwnCommands"
    actions   = ["iot:Subscribe"]
    resources = ["arn:aws:iot:${local.region}:${local.acct}:topicfilter/${var.topic_prefix}/$${iot:Connection.Thing.ThingName}/commands"]
  }

  statement {
    sid       = "ReceiveOwnCommands"
    actions   = ["iot:Receive"]
    resources = ["arn:aws:iot:${local.region}:${local.acct}:topic/${var.topic_prefix}/$${iot:Connection.Thing.ThingName}/commands"]
  }
}

resource "aws_iot_policy" "device" {
  name   = "${var.name_prefix}-station-gateway"
  policy = data.aws_iam_policy_document.device.json
  tags   = local.tags
}

# --- Rule: events -> SQS -----------------------------------------------------------------------------------------------

resource "aws_cloudwatch_log_group" "rule_errors" {
  name              = "/kifaru/${var.name_prefix}/iot-rule-errors"
  retention_in_days = var.log_retention_days
  tags              = local.tags
}

data "aws_iam_policy_document" "rule_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["iot.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.acct]
    }
  }
}

data "aws_iam_policy_document" "rule" {
  statement {
    actions   = ["sqs:SendMessage"]
    resources = [var.events_queue_arn]
  }

  statement {
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents", "logs:DescribeLogStreams"]
    resources = ["${aws_cloudwatch_log_group.rule_errors.arn}:*"]
  }
}

resource "aws_iam_role" "rule" {
  name               = "${var.name_prefix}-iot-rule"
  assume_role_policy = data.aws_iam_policy_document.rule_assume.json
  tags               = local.tags
}

resource "aws_iam_role_policy" "rule" {
  name   = "forward-events"
  role   = aws_iam_role.rule.id
  policy = data.aws_iam_policy_document.rule.json
}

resource "aws_iot_topic_rule" "station_events" {
  name        = "${replace(var.name_prefix, "-", "_")}_station_events"
  description = "Forward station gateway events to the SQS events queue"
  enabled     = true
  sql         = "SELECT *, topic(3) AS station_thing, timestamp() AS received_at_ms FROM '${var.topic_prefix}/+/events'"
  sql_version = "2016-03-23"

  sqs {
    queue_url  = var.events_queue_url
    role_arn   = aws_iam_role.rule.arn
    use_base64 = false
  }

  error_action {
    cloudwatch_logs {
      log_group_name = aws_cloudwatch_log_group.rule_errors.name
      role_arn       = aws_iam_role.rule.arn
    }
  }

  tags = local.tags
}

# --- Optional account-level IoT logging --------------------------------------------------------------------------------

data "aws_iam_policy_document" "logging_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["iot.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "logging" {
  count = var.enable_iot_logging ? 1 : 0

  name               = "${var.name_prefix}-iot-logging"
  assume_role_policy = data.aws_iam_policy_document.logging_assume.json
  tags               = local.tags
}

resource "aws_iam_role_policy_attachment" "logging" {
  count = var.enable_iot_logging ? 1 : 0

  role       = aws_iam_role.logging[0].name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSIoTLogging"
}

resource "aws_iot_logging_options" "this" {
  count = var.enable_iot_logging ? 1 : 0

  default_log_level = "WARN"
  role_arn          = aws_iam_role.logging[0].arn
}
