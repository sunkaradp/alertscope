output "role_arn" {
  description = "Set as aws.roleArn in the alertscope Helm values"
  value       = aws_iam_role.alertscope.arn
}
