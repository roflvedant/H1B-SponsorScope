output "github_actions_role_arn" {
  description = "Set this as the GitHub AWS_DEPLOY_ROLE_ARN variable."
  value       = aws_iam_role.github_deploy.arn
}

output "ecr_repository_url" {
  description = "Set this as the GitHub ECR_REPOSITORY_URL variable."
  value       = data.aws_ecr_repository.api.repository_url
}
