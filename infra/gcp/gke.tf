resource "google_service_account" "nodes" {
  account_id   = "gke-nodes"
  display_name = "GKE nodes"
}

resource "google_project_iam_member" "nodes" {
  for_each = toset([
    "roles/artifactregistry.reader",
    "roles/logging.logWriter",
    "roles/monitoring.metricWriter",
  ])
  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.nodes.email}"
}

resource "google_container_cluster" "main" {
  name     = var.cluster_name
  location = var.zone

  network    = google_compute_network.main.id
  subnetwork = google_compute_subnetwork.gke.id

  remove_default_node_pool = true
  initial_node_count       = 1
  deletion_protection      = false

  release_channel {
    channel = "REGULAR"
  }

  workload_identity_config {
    workload_pool = "${var.project_id}.svc.id.goog"
  }

  ip_allocation_policy {
    cluster_secondary_range_name  = "pods"
    services_secondary_range_name = "services"
  }

  # We run our own Prometheus/Loki, so keep Cloud Logging/Monitoring to the minimum.
  logging_config {
    enable_components = ["SYSTEM_COMPONENTS"]
  }
  monitoring_config {
    enable_components = ["SYSTEM_COMPONENTS"]
    managed_prometheus {
      enabled = false
    }
  }

  depends_on = [google_project_service.apis]
}

resource "google_container_node_pool" "default" {
  name       = "default"
  cluster    = google_container_cluster.main.id
  location   = var.zone
  node_count = var.node_count

  node_config {
    machine_type    = var.machine_type
    spot            = var.spot_nodes
    disk_size_gb    = 40
    disk_type       = "pd-standard"
    service_account = google_service_account.nodes.email
    oauth_scopes    = ["https://www.googleapis.com/auth/cloud-platform"]

    workload_metadata_config {
      mode = "GKE_METADATA"
    }
  }

  management {
    auto_repair  = true
    auto_upgrade = true
  }
}
