# AWS deployment

SponsorScope keeps its Next.js frontend on Vercel and moves the FastAPI API to
an always-provisioned AWS App Runner container. The existing PostgreSQL URL can
be reused for the first cutover; database migration to RDS can be handled
separately without blocking removal of the Render cold start.

## Prerequisites

- AWS CLI authenticated to your AWS account
- Terraform 1.7+
- Docker Desktop
- GitHub repository administrator access

Use `us-east-1` unless you intentionally change `aws_region`.

## 1. Create bootstrap resources

App Runner needs an ECR image before Terraform can create the service, so the
first deployment has a short two-stage bootstrap:

```powershell
Set-Location infra/aws
terraform init
terraform apply `
  -target=aws_ecr_repository.api `
  -target=aws_ecr_lifecycle_policy.api `
  -target=aws_s3_bucket.raw_snapshots `
  -target=aws_s3_bucket_public_access_block.raw_snapshots `
  -target=aws_s3_bucket_server_side_encryption_configuration.raw_snapshots `
  -target=aws_s3_bucket_lifecycle_configuration.raw_snapshots `
  -target=aws_secretsmanager_secret.database_url `
  -target=aws_secretsmanager_secret.jsearch_api_key
```

Record the account ID:

```powershell
$SponsorScopeAccount = aws sts get-caller-identity --query Account --output text
$SponsorScopeRegion = "us-east-1"
$SponsorScopeEcr = "$SponsorScopeAccount.dkr.ecr.$SponsorScopeRegion.amazonaws.com/sponsorscope-api"
```

## 2. Store production secrets

Find the two generated secret names in AWS Secrets Manager, then store the
current production values. Do not paste either value into Git or Terraform:

```powershell
aws secretsmanager put-secret-value --secret-id YOUR_DATABASE_SECRET_NAME --secret-string "YOUR_DATABASE_URL"
aws secretsmanager put-secret-value --secret-id YOUR_JSEARCH_SECRET_NAME --secret-string "YOUR_JSEARCH_API_KEY"
```

## 3. Push the first container

Run from the repository root:

```powershell
aws ecr get-login-password --region $SponsorScopeRegion | docker login --username AWS --password-stdin "$SponsorScopeAccount.dkr.ecr.$SponsorScopeRegion.amazonaws.com"
docker build -t "${SponsorScopeEcr}:latest" .
docker push "${SponsorScopeEcr}:latest"
```

## 4. Create App Runner and CI/CD

```powershell
Set-Location infra/aws
terraform apply
terraform output
```

Add these repository variables under **GitHub → Settings → Secrets and
variables → Actions → Variables**:

| Variable | Terraform output |
| --- | --- |
| `AWS_REGION` | `us-east-1` |
| `AWS_DEPLOY_ROLE_ARN` | `github_actions_role_arn` |
| `ECR_REPOSITORY_URL` | `ecr_repository_url` |
| `APP_RUNNER_SERVICE_ARN` | `app_runner_service_arn` |

The next push to `main` runs tests, builds and scans a new ECR image, and
deploys it to App Runner.

## 5. Point Vercel to AWS

Copy Terraform's `api_url` output. In Vercel, replace
`NEXT_PUBLIC_API_URL` with that URL for Production, Preview, and Development,
then redeploy the frontend. Do not include a trailing slash.

Verify:

```text
https://YOUR-APP-RUNNER-URL/health
```

Expected response:

```json
{"status":"healthy"}
```

Only remove the Render service after the Vercel site successfully completes a
fresh search and a cached repeat against AWS.

## Cost control

App Runner is intentionally configured with one provisioned instance to avoid
cold starts and a maximum of two active instances. Create an AWS Budget alert
before leaving the service running. Terraform outputs and AWS Cost Explorer
should be reviewed after the first full day of traffic.
