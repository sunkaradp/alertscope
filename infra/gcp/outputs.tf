output "get_credentials" {
  value = "gcloud container clusters get-credentials ${google_container_cluster.main.name} --zone ${var.zone} --project ${var.project_id}"
}

# Feed this into infra/aws so AWS trusts tokens from this cluster.
output "cluster_oidc_issuer" {
  value = "https://container.googleapis.com/v1/projects/${var.project_id}/locations/${var.zone}/clusters/${google_container_cluster.main.name}"
}

output "registry" {
  value = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.images.repository_id}"
}

output "app_service_account" {
  value = google_service_account.app.email
}

output "github_wif_provider" {
  value = google_iam_workload_identity_pool_provider.github.name
}

output "github_ci_service_account" {
  value = google_service_account.ci.email
}
