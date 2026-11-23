variable "project_id" {
  type = string
}

variable "region" {
  type    = string
  default = "europe-west3"
}

variable "zone" {
  type    = string
  default = "europe-west3-a"
}

variable "cluster_name" {
  type    = string
  default = "alertscope"
}

variable "machine_type" {
  type    = string
  default = "e2-standard-2"
}

variable "node_count" {
  type    = number
  default = 2
}

variable "spot_nodes" {
  description = "Spot VMs are ~60-90% cheaper. Fine for a demo cluster, not for prod."
  type        = bool
  default     = true
}

variable "github_repo" {
  description = "owner/name of the repo allowed to push images, e.g. sunkaradp/alertscope"
  type        = string
}

variable "app_namespace" {
  type    = string
  default = "alertscope"
}
