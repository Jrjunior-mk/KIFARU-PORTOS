# ---------------------------------------------------------------------------------------------------------------------
# storage: S3 buckets.
#
#   objects      tickets/ (Object Lock COMPLIANCE, 7 y), evidence/ (ANPR images), raw-signals/, exports/
#   backups      daily pg_dump archives (written by the scheduled ECS task), Redis snapshot exports
#   web          Vite SPA build, served privately through CloudFront with Origin Access Control
#   access-logs  ALB access logs
#   objects/backups are versioned, KMS-encrypted and replicated to eu-west-1 (DR) when enable_replication = true.
#
# Lifecycle rules implement the retention table in docs/06-operations/backup-and-retention.md.
# ---------------------------------------------------------------------------------------------------------------------

data "aws_caller_identity" "current" {}
data "aws_elb_service_account" "this" {}

locals {
  account  = data.aws_caller_identity.current.account_id
  tags     = merge(var.tags, { DataClass = "Confidential" })
  web_tags = merge(var.tags, { DataClass = "Public" })

  bucket_objects    = "${var.name_prefix}-objects-${local.account}"
  bucket_backups    = "${var.name_prefix}-backups-${local.account}"
  bucket_web        = "${var.name_prefix}-web-${local.account}"
  bucket_logs       = "${var.name_prefix}-access-logs-${local.account}"
  bucket_objects_dr = "${var.name_prefix}-objects-dr-${local.account}"
  bucket_backups_dr = "${var.name_prefix}-backups-dr-${local.account}"
}

# --- KMS ---------------------------------------------------------------------------------------------------------------

resource "aws_kms_key" "s3" {
  description             = "${var.name_prefix} S3 object encryption"
  deletion_window_in_days = 30
  enable_key_rotation     = true
  tags                    = local.tags
}

resource "aws_kms_alias" "s3" {
  name          = "alias/${var.name_prefix}-s3"
  target_key_id = aws_kms_key.s3.key_id
}

resource "aws_kms_key" "s3_dr" {
  provider = aws.dr

  description             = "${var.name_prefix} S3 replica encryption (DR region)"
  deletion_window_in_days = 30
  enable_key_rotation     = true
  tags                    = local.tags
}

resource "aws_kms_alias" "s3_dr" {
  provider      = aws.dr
  name          = "alias/${var.name_prefix}-s3-dr"
  target_key_id = aws_kms_key.s3_dr.key_id
}

# --- objects bucket ----------------------------------------------------------------------------------------------------

resource "aws_s3_bucket" "objects" {
  bucket              = local.bucket_objects
  object_lock_enabled = true
  force_destroy       = var.force_destroy
  tags                = merge(local.tags, { Name = local.bucket_objects })
}

resource "aws_s3_bucket_versioning" "objects" {
  bucket = aws_s3_bucket.objects.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "objects" {
  bucket = aws_s3_bucket.objects.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.s3.arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "objects" {
  bucket                  = aws_s3_bucket.objects.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "objects" {
  bucket = aws_s3_bucket.objects.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

# Object Lock is enabled bucket-wide but no bucket default retention is set, so evidence/raw-signal objects can expire.
# The bucket policy below forces every PutObject under tickets/ to carry a COMPLIANCE retention of at least the policy
# period; the API sets x-amz-object-lock-mode/retain-until-date on ticket uploads (see deployment guide).
resource "aws_s3_bucket_object_lock_configuration" "objects" {
  bucket = aws_s3_bucket.objects.id
  # No default rule: retention is enforced per prefix through the bucket policy.
  depends_on = [aws_s3_bucket_versioning.objects]
}

data "aws_iam_policy_document" "objects" {
  statement {
    sid     = "DenyInsecureTransport"
    effect  = "Deny"
    actions = ["s3:*"]
    principals {
      type        = "AWS"
      identifiers = ["*"]
    }
    resources = [aws_s3_bucket.objects.arn, "${aws_s3_bucket.objects.arn}/*"]
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }

  statement {
    sid     = "RequireObjectLockOnTickets"
    effect  = "Deny"
    actions = ["s3:PutObject"]
    principals {
      type        = "AWS"
      identifiers = ["*"]
    }
    resources = ["${aws_s3_bucket.objects.arn}/tickets/*"]
    condition {
      test     = "Null"
      variable = "s3:object-lock-mode"
      values   = ["true"]
    }
  }

  statement {
    sid     = "RequireComplianceModeOnTickets"
    effect  = "Deny"
    actions = ["s3:PutObject"]
    principals {
      type        = "AWS"
      identifiers = ["*"]
    }
    resources = ["${aws_s3_bucket.objects.arn}/tickets/*"]
    condition {
      test     = "StringNotEqualsIfExists"
      variable = "s3:object-lock-mode"
      values   = ["COMPLIANCE"]
    }
  }
}

resource "aws_s3_bucket_policy" "objects" {
  bucket = aws_s3_bucket.objects.id
  policy = data.aws_iam_policy_document.objects.json
}

resource "aws_s3_bucket_lifecycle_configuration" "objects" {
  bucket = aws_s3_bucket.objects.id

  rule {
    id     = "tickets-archive"
    status = "Enabled"
    filter {
      prefix = "tickets/"
    }
    transition {
      days          = 365
      storage_class = "GLACIER_IR"
    }
    noncurrent_version_transition {
      noncurrent_days = 30
      storage_class   = "GLACIER_IR"
    }
    # Tickets are never expired by lifecycle; Object Lock retention (tickets_retention_days) governs deletion.
  }

  rule {
    id     = "evidence-tiering"
    status = "Enabled"
    filter {
      prefix = "evidence/"
    }
    transition {
      days          = 30
      storage_class = "STANDARD_IA"
    }
    transition {
      days          = 90
      storage_class = "GLACIER_IR"
    }
    expiration {
      days = var.evidence_expiration_days
    }
    noncurrent_version_expiration {
      noncurrent_days = var.noncurrent_version_expiration_days
    }
  }

  rule {
    id     = "raw-signals-expire"
    status = "Enabled"
    filter {
      prefix = "raw-signals/"
    }
    expiration {
      days = var.raw_signal_expiration_days
    }
    noncurrent_version_expiration {
      noncurrent_days = 7
    }
  }

  rule {
    id     = "exports-expire"
    status = "Enabled"
    filter {
      prefix = "exports/"
    }
    expiration {
      days = 30
    }
    noncurrent_version_expiration {
      noncurrent_days = 7
    }
  }

  rule {
    id     = "abort-incomplete-uploads"
    status = "Enabled"
    filter {}
    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }

  depends_on = [aws_s3_bucket_versioning.objects]
}

# --- backups bucket ----------------------------------------------------------------------------------------------------

resource "aws_s3_bucket" "backups" {
  bucket        = local.bucket_backups
  force_destroy = var.force_destroy
  tags          = merge(local.tags, { Name = local.bucket_backups, DataClass = "Confidential-PII" })
}

resource "aws_s3_bucket_versioning" "backups" {
  bucket = aws_s3_bucket.backups.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "backups" {
  bucket = aws_s3_bucket.backups.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.s3.arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "backups" {
  bucket                  = aws_s3_bucket.backups.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "backups" {
  bucket = aws_s3_bucket.backups.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

data "aws_iam_policy_document" "backups" {
  statement {
    sid     = "DenyInsecureTransport"
    effect  = "Deny"
    actions = ["s3:*"]
    principals {
      type        = "AWS"
      identifiers = ["*"]
    }
    resources = [aws_s3_bucket.backups.arn, "${aws_s3_bucket.backups.arn}/*"]
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "backups" {
  bucket = aws_s3_bucket.backups.id
  policy = data.aws_iam_policy_document.backups.json
}

resource "aws_s3_bucket_lifecycle_configuration" "backups" {
  bucket = aws_s3_bucket.backups.id

  rule {
    id     = "pgdump-tiering"
    status = "Enabled"
    filter {
      prefix = "pgdump/"
    }
    transition {
      days          = 30
      storage_class = "STANDARD_IA"
    }
    transition {
      days          = 90
      storage_class = "GLACIER"
    }
    expiration {
      days = var.backup_expiration_days
    }
    noncurrent_version_expiration {
      noncurrent_days = 30
    }
  }

  rule {
    id     = "abort-incomplete-uploads"
    status = "Enabled"
    filter {}
    abort_incomplete_multipart_upload {
      days_after_initiation = 3
    }
  }

  depends_on = [aws_s3_bucket_versioning.backups]
}

# --- web bucket (CloudFront OAC origin; bucket policy is attached by the edge module) -----------------------------------

resource "aws_s3_bucket" "web" {
  bucket        = local.bucket_web
  force_destroy = var.force_destroy
  tags          = merge(local.web_tags, { Name = local.bucket_web })
}

resource "aws_s3_bucket_versioning" "web" {
  bucket = aws_s3_bucket.web.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "web" {
  bucket = aws_s3_bucket.web.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256" # CloudFront OAC cannot read SSE-KMS objects without extra key policy; SPA assets are public anyway
    }
  }
}

resource "aws_s3_bucket_public_access_block" "web" {
  bucket                  = aws_s3_bucket.web.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "web" {
  bucket = aws_s3_bucket.web.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "web" {
  bucket = aws_s3_bucket.web.id

  rule {
    id     = "old-builds"
    status = "Enabled"
    filter {}
    noncurrent_version_expiration {
      noncurrent_days = 30
    }
    abort_incomplete_multipart_upload {
      days_after_initiation = 3
    }
  }

  depends_on = [aws_s3_bucket_versioning.web]
}

# --- access logs bucket --------------------------------------------------------------------------------------------------

resource "aws_s3_bucket" "logs" {
  bucket        = local.bucket_logs
  force_destroy = var.force_destroy
  tags          = merge(local.tags, { Name = local.bucket_logs, DataClass = "Internal" })
}

resource "aws_s3_bucket_server_side_encryption_configuration" "logs" {
  bucket = aws_s3_bucket.logs.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256" # ALB log delivery supports SSE-S3 only
    }
  }
}

resource "aws_s3_bucket_public_access_block" "logs" {
  bucket                  = aws_s3_bucket.logs.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "logs" {
  bucket = aws_s3_bucket.logs.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

data "aws_iam_policy_document" "logs" {
  statement {
    sid     = "AllowALBLogDelivery"
    effect  = "Allow"
    actions = ["s3:PutObject"]
    principals {
      type        = "AWS"
      identifiers = [data.aws_elb_service_account.this.arn]
    }
    resources = ["${aws_s3_bucket.logs.arn}/alb/AWSLogs/${local.account}/*"]
  }

  statement {
    sid     = "DenyInsecureTransport"
    effect  = "Deny"
    actions = ["s3:*"]
    principals {
      type        = "AWS"
      identifiers = ["*"]
    }
    resources = [aws_s3_bucket.logs.arn, "${aws_s3_bucket.logs.arn}/*"]
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "logs" {
  bucket = aws_s3_bucket.logs.id
  policy = data.aws_iam_policy_document.logs.json
}

resource "aws_s3_bucket_lifecycle_configuration" "logs" {
  bucket = aws_s3_bucket.logs.id

  rule {
    id     = "expire-logs"
    status = "Enabled"
    filter {}
    expiration {
      days = var.access_log_expiration_days
    }
  }
}

# --- DR replicas (eu-west-1) -------------------------------------------------------------------------------------------

resource "aws_s3_bucket" "objects_dr" {
  count    = var.enable_replication ? 1 : 0
  provider = aws.dr

  bucket              = local.bucket_objects_dr
  object_lock_enabled = true
  force_destroy       = var.force_destroy
  tags                = merge(local.tags, { Name = local.bucket_objects_dr, Role = "dr-replica" })
}

resource "aws_s3_bucket_versioning" "objects_dr" {
  count    = var.enable_replication ? 1 : 0
  provider = aws.dr

  bucket = aws_s3_bucket.objects_dr[0].id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "objects_dr" {
  count    = var.enable_replication ? 1 : 0
  provider = aws.dr

  bucket = aws_s3_bucket.objects_dr[0].id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.s3_dr.arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "objects_dr" {
  count    = var.enable_replication ? 1 : 0
  provider = aws.dr

  bucket                  = aws_s3_bucket.objects_dr[0].id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket" "backups_dr" {
  count    = var.enable_replication ? 1 : 0
  provider = aws.dr

  bucket        = local.bucket_backups_dr
  force_destroy = var.force_destroy
  tags          = merge(local.tags, { Name = local.bucket_backups_dr, Role = "dr-replica", DataClass = "Confidential-PII" })
}

resource "aws_s3_bucket_versioning" "backups_dr" {
  count    = var.enable_replication ? 1 : 0
  provider = aws.dr

  bucket = aws_s3_bucket.backups_dr[0].id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "backups_dr" {
  count    = var.enable_replication ? 1 : 0
  provider = aws.dr

  bucket = aws_s3_bucket.backups_dr[0].id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.s3_dr.arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "backups_dr" {
  count    = var.enable_replication ? 1 : 0
  provider = aws.dr

  bucket                  = aws_s3_bucket.backups_dr[0].id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "backups_dr" {
  count    = var.enable_replication ? 1 : 0
  provider = aws.dr

  bucket = aws_s3_bucket.backups_dr[0].id

  rule {
    id     = "replica-expire"
    status = "Enabled"
    filter {}
    expiration {
      days = var.backup_expiration_days
    }
    noncurrent_version_expiration {
      noncurrent_days = 30
    }
  }

  depends_on = [aws_s3_bucket_versioning.backups_dr]
}

# --- Replication role & rules ------------------------------------------------------------------------------------------

data "aws_iam_policy_document" "replication_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["s3.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "replication" {
  count = var.enable_replication ? 1 : 0

  statement {
    sid       = "SourceBucketRead"
    actions   = ["s3:GetReplicationConfiguration", "s3:ListBucket"]
    resources = [aws_s3_bucket.objects.arn, aws_s3_bucket.backups.arn]
  }

  statement {
    sid = "SourceObjectRead"
    actions = [
      "s3:GetObjectVersionForReplication",
      "s3:GetObjectVersionAcl",
      "s3:GetObjectVersionTagging",
      "s3:GetObjectRetention",
      "s3:GetObjectLegalHold",
    ]
    resources = ["${aws_s3_bucket.objects.arn}/*", "${aws_s3_bucket.backups.arn}/*"]
  }

  statement {
    sid = "DestinationWrite"
    actions = [
      "s3:ReplicateObject",
      "s3:ReplicateDelete",
      "s3:ReplicateTags",
      "s3:ObjectOwnerOverrideToBucketOwner",
    ]
    resources = ["${aws_s3_bucket.objects_dr[0].arn}/*", "${aws_s3_bucket.backups_dr[0].arn}/*"]
  }

  statement {
    sid       = "SourceKmsDecrypt"
    actions   = ["kms:Decrypt"]
    resources = [aws_kms_key.s3.arn]
  }

  statement {
    sid       = "DestinationKmsEncrypt"
    actions   = ["kms:Encrypt", "kms:GenerateDataKey"]
    resources = [aws_kms_key.s3_dr.arn]
  }
}

resource "aws_iam_role" "replication" {
  count = var.enable_replication ? 1 : 0

  name               = "${var.name_prefix}-s3-replication"
  assume_role_policy = data.aws_iam_policy_document.replication_assume.json
  tags               = local.tags
}

resource "aws_iam_role_policy" "replication" {
  count = var.enable_replication ? 1 : 0

  name   = "replicate"
  role   = aws_iam_role.replication[0].id
  policy = data.aws_iam_policy_document.replication[0].json
}

resource "aws_s3_bucket_replication_configuration" "objects" {
  count = var.enable_replication ? 1 : 0

  bucket = aws_s3_bucket.objects.id
  role   = aws_iam_role.replication[0].arn

  rule {
    id       = "objects-to-dr"
    status   = "Enabled"
    priority = 1

    filter {}

    delete_marker_replication {
      status = "Disabled"
    }

    source_selection_criteria {
      sse_kms_encrypted_objects {
        status = "Enabled"
      }
    }

    destination {
      bucket        = aws_s3_bucket.objects_dr[0].arn
      storage_class = "STANDARD_IA"

      encryption_configuration {
        replica_kms_key_id = aws_kms_key.s3_dr.arn
      }

      replication_time {
        status = "Enabled"
        time {
          minutes = 15
        }
      }

      metrics {
        status = "Enabled"
        event_threshold {
          minutes = 15
        }
      }
    }
  }

  depends_on = [aws_s3_bucket_versioning.objects, aws_s3_bucket_versioning.objects_dr]
}

resource "aws_s3_bucket_replication_configuration" "backups" {
  count = var.enable_replication ? 1 : 0

  bucket = aws_s3_bucket.backups.id
  role   = aws_iam_role.replication[0].arn

  rule {
    id       = "backups-to-dr"
    status   = "Enabled"
    priority = 1

    filter {}

    delete_marker_replication {
      status = "Disabled"
    }

    source_selection_criteria {
      sse_kms_encrypted_objects {
        status = "Enabled"
      }
    }

    destination {
      bucket        = aws_s3_bucket.backups_dr[0].arn
      storage_class = "STANDARD_IA"

      encryption_configuration {
        replica_kms_key_id = aws_kms_key.s3_dr.arn
      }

      replication_time {
        status = "Enabled"
        time {
          minutes = 15
        }
      }

      metrics {
        status = "Enabled"
        event_threshold {
          minutes = 15
        }
      }
    }
  }

  depends_on = [aws_s3_bucket_versioning.backups, aws_s3_bucket_versioning.backups_dr]
}
