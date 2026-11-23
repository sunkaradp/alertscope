resource "google_artifact_registry_repository" "images" {
  repository_id = "alertscope"
  location      = var.region
  format        = "DOCKER"

  cleanup_policies {
    id     = "keep-last-10"
    action = "KEEP"
    most_recent_versions {
      keep_count = 10
    }
  }
  cleanup_policies {
    id     = "delete-old"
    action = "DELETE"
    condition {
      older_than = "1209600s"
    }
  }

  depends_on = [google_project_service.apis]
}
