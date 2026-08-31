variable "aws_region" {
  description = "AWS region containing SponsorScope ECS and ECR resources."
  type        = string
  default     = "us-east-2"
}

variable "github_oidc_subject_prefix" {
  description = "Immutable GitHub OIDC subject prefix containing owner and repository IDs."
  type        = string
  default     = "repo:roflvedant@160684790/H1B-SponsorScope@1335470046"
}

variable "ecr_repository_name" {
  description = "Existing ECR repository used by the API."
  type        = string
  default     = "sponsorscope-api"
}

variable "ecs_cluster_name" {
  description = "Existing ECS cluster used by SponsorScope."
  type        = string
  default     = "default"
}

variable "ecs_service_name" {
  description = "Existing ECS Express Mode service."
  type        = string
  default     = "sponsorscope-api"
}
