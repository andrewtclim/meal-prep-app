# Values a later GitHub Actions workflow will need. No secrets — only resource names.

output "artifact_registry_repository" {
  description = "Docker repo path prefix (region-docker.pkg.dev/project/api)"
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.api.repository_id}"
}

output "github_deploy_service_account_email" {
  description = "Service account email for GitHub Actions to impersonate"
  value       = google_service_account.github_deploy.email
}

output "github_wif_provider" {
  description = "Full resource name of the Workload Identity provider (workload_identity_provider in Actions)"
  value       = google_iam_workload_identity_pool_provider.github.name
}
