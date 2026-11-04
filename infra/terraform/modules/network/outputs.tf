output "vpc_id" {
  description = "VPC ID."
  value       = aws_vpc.this.id
}

output "vpc_cidr" {
  description = "VPC CIDR block."
  value       = aws_vpc.this.cidr_block
}

output "public_subnet_ids" {
  description = "Public subnet IDs (ALB, NAT)."
  value       = aws_subnet.public[*].id
}

output "private_subnet_ids" {
  description = "Private subnet IDs (ECS tasks, RDS, ElastiCache)."
  value       = aws_subnet.private[*].id
}

output "availability_zones" {
  description = "AZs in use."
  value       = local.azs
}

output "endpoint_security_group_id" {
  description = "Security group attached to interface endpoints (null when endpoints are disabled)."
  value       = var.enable_interface_endpoints ? aws_security_group.endpoints[0].id : null
}
