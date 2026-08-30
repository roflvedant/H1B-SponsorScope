# AWS ECS deployment

SponsorScope runs its Next.js frontend on Vercel and its FastAPI container on
Amazon ECS Express Mode in `us-east-2`. PostgreSQL remains externally hosted
during this phase. ECS retrieves the database URL and JSearch key from AWS
Secrets Manager whenever a task starts.

## Existing production resources

| Resource | Value |
| --- | --- |
| ECR repository | `sponsorscope-api` |
| ECS cluster | `default` |
| ECS service | `sponsorscope-api` |
| Container port | `8000` |
| Health endpoint | `/health` |

The service uses one minimum task and two maximum tasks. Keeping one task
running avoids the cold starts previously encountered on Render.

## One-time GitHub OIDC setup

The Terraform in this directory manages only the least-privilege GitHub
deployment identity. It deliberately does not recreate or take ownership of
the console-created ECS Express Mode service.

Run from `infra/aws` while authenticated to account `333534067159`:

```powershell
terraform init
terraform apply
terraform output
```

If the account already contains the GitHub Actions OIDC provider, import it
before applying instead of creating a duplicate:

```powershell
terraform import aws_iam_openid_connect_provider.github `
  arn:aws:iam::333534067159:oidc-provider/token.actions.githubusercontent.com
```

## GitHub repository variables

Under **Settings → Secrets and variables → Actions → Variables**, add:

| Variable | Value |
| --- | --- |
| `AWS_REGION` | `us-east-2` |
| `AWS_DEPLOY_ROLE_ARN` | Terraform `github_actions_role_arn` output |
| `ECR_REPOSITORY_URL` | `333534067159.dkr.ecr.us-east-2.amazonaws.com/sponsorscope-api` |
| `ECS_CLUSTER` | `default` |
| `ECS_SERVICE` | `sponsorscope-api` |

No AWS access key or secret access key belongs in GitHub.

## Automated deployment

Every push to `main` performs these steps:

1. Install dependencies and run the backend tests.
2. Build the Docker image.
3. Push immutable commit-SHA and `latest` tags to ECR.
4. Force the existing ECS service to start a deployment.
5. Wait for ECS to report a stable service.

The deployment job safely skips until `AWS_DEPLOY_ROLE_ARN` is configured.
After configuring the variables, run the workflow manually once from the
GitHub **Actions** tab.

## Production verification

Verify the API before testing the Vercel application:

```text
https://sp-1bbff7add6c94b48a8f5e322eddd4c9c.ecs.us-east-2.on.aws/health
```

Expected response:

```json
{"status":"healthy"}
```

The Vercel `NEXT_PUBLIC_API_URL` must use the same URL without `/health` and
without a trailing slash.
