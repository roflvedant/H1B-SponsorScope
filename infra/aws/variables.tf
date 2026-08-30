variable "aws_region" {
  description = "AWS region for SponsorScope."
  type        = string
  default     = "us-east-1"
}

variable "github_repository" {
  description = "GitHub repository allowed to deploy, for example roflvedant/H1B-SponsorScope."
  type        = string
  default     = "roflvedant/H1B-SponsorScope"
}

variable "frontend_origins" {
  description = "Comma-separated browser origins allowed by FastAPI."
  type        = string
  default     = "https://h1-b-sponsor-scope.vercel.app,https://h1-b-sponsor-scope-git-main-vedant-patil1.vercel.app"
}
