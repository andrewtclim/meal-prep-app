variable "project_id" {
  type        = string
  description = "GCP project ID"
}

variable "region" {
  type        = string
  description = "Default GCP region"
  default     = "us-west1"
}

variable "github_repository" {
  type        = string
  description = "GitHub repo (owner/name) allowed to deploy via Workload Identity Federation"
  default     = "andrewtclim/meal-prep-app"
}
