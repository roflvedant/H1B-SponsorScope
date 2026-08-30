variable "aws_region" {
  description = "AWS region containing SponsorScope ECS and ECR resources."
  type        = string
  default     = "us-east-2"
}

variable "github_repository" {
  description = "GitHub repository permitted to assume the deployment role."
  type        = string
  default     = "roflvedant/H1B-SponsorScope"
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
