data "aws_caller_identity" "current" {}

locals {
  issuer = trimprefix(var.cluster_oidc_issuer, "https://")
}

# AWS trusts tokens signed by the GKE cluster. GKE publishes its JWKS at
# <issuer>/.well-known/openid-configuration, so no keys are copied anywhere.
resource "aws_iam_openid_connect_provider" "gke" {
  url            = var.cluster_oidc_issuer
  client_id_list = ["sts.amazonaws.com"]
}

data "aws_iam_policy_document" "trust" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.gke.arn]
    }
    condition {
      test     = "StringEquals"
      variable = "${local.issuer}:aud"
      values   = ["sts.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "${local.issuer}:sub"
      values   = ["system:serviceaccount:${var.service_account}"]
    }
  }
}

resource "aws_iam_role" "alertscope" {
  name                 = "alertscope-bedrock"
  assume_role_policy   = data.aws_iam_policy_document.trust.json
  max_session_duration = 3600
}

data "aws_iam_policy_document" "bedrock" {
  statement {
    actions = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
    resources = [
      "arn:aws:bedrock:*::foundation-model/anthropic.*",
      "arn:aws:bedrock:*:${data.aws_caller_identity.current.account_id}:inference-profile/*",
    ]
  }
}

resource "aws_iam_role_policy" "bedrock" {
  name   = "invoke-bedrock"
  role   = aws_iam_role.alertscope.id
  policy = data.aws_iam_policy_document.bedrock.json
}

resource "aws_budgets_budget" "monthly" {
  name         = "alertscope-monthly"
  budget_type  = "COST"
  limit_amount = tostring(var.monthly_budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.budget_email]
  }
}
