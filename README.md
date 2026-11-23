# alertscope

When an alert fires, the first ten minutes usually go the same way: open Grafana, find
the pod, check restarts and memory, grep the logs, look at events. alertscope does that
first pass automatically and posts what it found to Slack, so whoever is on call starts
from a hypothesis instead of a blank screen.

It sits behind Alertmanager as a webhook receiver. For each firing alert it:

1. re-runs the alert's own PromQL over the last 15 minutes, plus restarts / memory /
   CPU / last termination reason if the alert points at a pod
2. pulls error-looking and most recent log lines for the same pod from Loki
3. reads pod status and events from the Kubernetes API
4. sends all of that to an LLM (Claude on AWS Bedrock, or Gemini on Vertex AI) and asks
   for a likely cause, the evidence for it and next steps, as JSON
5. posts the result to Slack, writes it to stdout as one JSON line (so it ends up in
   Loki next to everything else), and keeps the last 50 at `GET /analyses`

```
 Prometheus ──alert──> Alertmanager ──webhook──> alertscope ──> Slack
     ^                                              │
     │            PromQL / LogQL / k8s API          │
     └──────────────── Loki <───────────────────────┤
                       k8s API <────────────────────┤
                                                    └──> Bedrock (Claude) | Vertex (Gemini)
```

Example output for the demo app in `leak` mode:

> **BreakerMemoryNearLimit** `demo / breaker-6c9d7f-x2k4p`
> Memory grows by ~8 MiB every half second until the container is OOM killed at its 192Mi limit.
> likely cause: *unbounded in-memory cache* | confidence: high
>
> 1. `kubectl -n demo logs breaker-6c9d7f-x2k4p --previous | tail`
> 2. Check what `cache warmup` stores and add a size cap
> 3. Raising the limit will only delay the next OOM

## Running it locally

Needs Docker. Everything runs in compose: a demo service that breaks on request,
Prometheus, Alertmanager, Loki, Alloy, Grafana and alertscope.

```bash
cp .env.example .env      # stub LLM by default, no cloud account needed
make up
make break MODE=errors    # or slow / leak / crash
# ~1 minute later, open http://localhost:3000/d/alertscope
make fix
```

`make fire` skips the Prometheus/Alertmanager wait and posts a sample alert directly.

The `stub` provider is a few regexes, just enough to exercise the pipeline. Set
`ALERTSCOPE_LLM_PROVIDER=bedrock` or `vertex` in `.env` for real output.

## Deploying (GKE + Bedrock)

The cluster runs on GKE. The LLM is Claude on Bedrock, called from the GKE pod
**without any AWS access keys**:

- the pod gets a projected service account token with audience `sts.amazonaws.com`
- AWS IAM has an OIDC provider pointing at the GKE cluster's issuer URL, so it can
  verify that token
- the role trust policy only accepts `system:serviceaccount:alertscope:alertscope`
- boto3 picks up `AWS_ROLE_ARN` + `AWS_WEB_IDENTITY_TOKEN_FILE` and calls
  `AssumeRoleWithWebIdentity` on its own

GitHub Actions pushes images the same way, through GCP Workload Identity Federation,
so there are no JSON keys in repo secrets either.

```bash
# 1. GCP: network, GKE, Artifact Registry, service accounts
cd infra/gcp
cp terraform.tfvars.example terraform.tfvars   # edit
terraform init -backend-config="bucket=<project>-tfstate"
terraform apply

# 2. AWS: OIDC provider for the cluster, Bedrock role, budget alert
cd ../aws
cp terraform.tfvars.example terraform.tfvars   # cluster_oidc_issuer from step 1
terraform init -backend-config="bucket=<state-bucket>" -backend-config="region=eu-central-1"
terraform apply

# 3. Argo CD, then everything else comes from gitops/
$(terraform -chdir=../gcp output -raw get_credentials)
kubectl create ns argocd
kubectl apply -n argocd --server-side -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml
kubectl create ns alertscope
kubectl -n alertscope create secret generic alertscope-slack --from-literal=SLACK_WEBHOOK_URL=https://hooks.slack.com/...
kubectl apply -f gitops/root.yaml
```

Before step 3, replace `YOUR_USER`, `PROJECT_ID` and `AWS_ACCOUNT_ID` in `gitops/`, and
set the repo variables `GCP_WIF_PROVIDER`, `GCP_CI_SA` and `REGISTRY` from the
Terraform outputs. After that, every push to `main` that touches `app/` or `demo/`
builds both images and bumps the tags in `gitops/values/`, and Argo CD rolls them out.

Bedrock model access for Anthropic models has to be enabled once in the AWS console
for your account and region.

Switching to Gemini instead: set `config.llm.provider: vertex` and
`config.vertex.project` in `gitops/values/alertscope.yaml`. The Workload Identity
binding for Vertex is already in `infra/gcp`.

## Cost

Two `e2-standard-2` spot nodes plus disks come to roughly $30-45/month
(the zonal cluster fee is covered by the GKE free tier). Bedrock with Haiku is a
fraction of a cent per alert. `infra/aws` sets a $10 monthly budget alert. Scale the
node pool to 0 when you're not using it:

```bash
gcloud container clusters resize alertscope --node-pool default --num-nodes 0 --zone europe-west3-a
```

## Grafana

There's no separate UI. Analyses go to Loki as JSON log lines and the chart ships a
dashboard (ConfigMap picked up by the kube-prometheus-stack Grafana sidecar; the
compose stack provisions it from the same file):

- top row: analyses, share with high confidence, median analysis time, LLM tokens,
  LLM and collector errors for the selected time range
- alerts received vs analysed vs skipped, and LLM latency p50/p95 per provider
- a table of the latest analyses (severity, alert, pod, likely cause, next steps)
- the full investigations as log lines, filterable like any other Loki query

To query them yourself:

```logql
{container="alertscope"} | json | event="analysis" | confidence="high"
```

Source: [`charts/alertscope/dashboards/alertscope.json`](charts/alertscope/dashboards/alertscope.json).

## Metrics

alertscope exposes its own metrics at `/metrics/` and ships a ServiceMonitor:

| metric | |
|---|---|
| `alertscope_alerts_received_total{status}` | everything Alertmanager sent |
| `alertscope_alerts_skipped_total{reason}` | resolved, or same fingerprint inside the cooldown |
| `alertscope_analyses_total{result,confidence}` | finished analyses |
| `alertscope_analysis_seconds` | collect + LLM + notify |
| `alertscope_llm_seconds{provider}` | LLM latency only |
| `alertscope_llm_tokens_total{provider,direction}` | for cost tracking |
| `alertscope_collector_errors_total{collector}` | Prometheus/Loki/k8s failures |

## Configuration

All settings are env vars with the `ALERTSCOPE_` prefix, see
[`config.py`](app/src/alertscope/config.py). The ones you'll most likely change:

| var | default | |
|---|---|---|
| `LLM_PROVIDER` | `stub` | `bedrock`, `vertex` or `stub` |
| `BEDROCK_MODEL_ID` | Claude Haiku 4.5 (EU inference profile) | any Bedrock chat model |
| `VERTEX_MODEL` | `gemini-2.5-flash` | |
| `LOKI_LABELS` | `["namespace","pod","container"]` | alert labels that are also Loki stream labels |
| `LOOKBACK_MINUTES` | `15` | |
| `COOLDOWN_MINUTES` | `30` | per alert fingerprint |
| `KUBE_ENABLED` | `false` | read pod status/events; the chart turns this on |

## Layout

```
app/             FastAPI service, collectors, LLM providers, tests
demo/breaker/    service that fails on demand (errors, slow, leak, crash)
charts/          Helm charts for both
deploy/local/    docker compose stack
infra/gcp/       VPC, GKE, Artifact Registry, Workload Identity (pod + GitHub)
infra/aws/       OIDC trust for the GKE cluster, Bedrock role, budget
gitops/          Argo CD app-of-apps: kube-prometheus-stack, Loki, Alloy, alertscope
```

## Limitations / next

- Read-only on purpose. It suggests commands, it doesn't run them.
- Single replica, history is in memory. Fine for one cluster.
- One LLM call per alert. A tool-calling loop where the model asks for the next query
  would handle multi-service incidents better.
- No tracing data yet (Tempo would be the obvious next collector).
- Doesn't learn from past incidents. Storing analyses with the eventual fix and
  retrieving similar ones is the next step I'd take.
#   a l r e t s c o p e  
 