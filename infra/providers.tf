terraform {
  backend "gcs" {
    bucket = "meal-prep-app-510920-tfstate"
    prefix = "infra"
  }
}
provider "google" {
  project = var.project_id
  region  = var.region
}