# Docker image repo for the API (generic name — DECISIONS #13)
resource "google_artifact_registry_repository" "api" {
  location      = var.region
  repository_id = "api"
  description   = "Container images for the API service"
  format        = "DOCKER"

  depends_on = [google_project_service.services]
}