terraform {
  required_version = ">= 1.9.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.100"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.7"
    }
  }

  # Partial backend configuration: supply bucket/key/region/table via `terraform init -backend-config=backend.hcl`
  # (see backend.hcl.example). Keeping it partial lets each root share this file verbatim.
  backend "s3" {}
}
