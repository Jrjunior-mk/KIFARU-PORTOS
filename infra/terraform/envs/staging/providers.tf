provider "aws" {
  region = var.aws_region

  default_tags {
    tags = local.default_tags
  }
}

# CloudFront certificates and WAF (CLOUDFRONT scope) must live in us-east-1.
provider "aws" {
  alias  = "us_east_1"
  region = "us-east-1"

  default_tags {
    tags = local.default_tags
  }
}

# Disaster-recovery region: S3 replicas and replicated RDS automated backups.
provider "aws" {
  alias  = "dr"
  region = var.dr_region

  default_tags {
    tags = merge(local.default_tags, { Role = "dr" })
  }
}
