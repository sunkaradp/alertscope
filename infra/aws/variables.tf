variable "region" {
  type    = string
  default = "eu-central-1"
}

variable "cluster_oidc_issuer" {
  description = "Output cluster_oidc_issuer from infra/gcp"
  type        = string
}

variable "service_account" {
  description = "namespace:name of the Kubernetes service account allowed to assume the role"
  type        = string
  default     = "alertscope:alertscope"
}

variable "monthly_budget_usd" {
  type    = number
  default = 10
}

variable "budget_email" {
  type = string
}
