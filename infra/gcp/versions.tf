terraform {
  required_version = ">= 1.6"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }
  # Bucket has to exist before init:
  #   gsutil mb -l europe-west3 gs://<project>-tfstate
  backend "gcs" {
    prefix = "alertscope/gcp"
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}
