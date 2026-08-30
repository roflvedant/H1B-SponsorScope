output "ecr_repository_url" { value = aws_ecr_repository.api.repository_url }
output "app_runner_service_arn" { value = aws_apprunner_service.api.arn }
output "api_url" { value = "https://${aws_apprunner_service.api.service_url}" }
output "raw_snapshot_bucket" { value = aws_s3_bucket.raw_snapshots.id }
output "github_actions_role_arn" { value = aws_iam_role.github_deploy.arn }
output "database_secret_arn" { value = aws_secretsmanager_secret.database_url.arn }
output "jsearch_secret_arn" { value = aws_secretsmanager_secret.jsearch_api_key.arn }
