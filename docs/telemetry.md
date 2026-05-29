# Claude Code Telemetry

Two ingestion paths feed the **Claude Code Analytics** panel on the dashboard:

| Path | When to use | Works with Bedrock / Vertex / proxy? |
|------|-------------|---------------------------------------|
| Anthropic Admin API (`sk-ant-admin-*`) | First-party Console organisations only | ❌ — backend must be `api.anthropic.com` |
| **OTLP receiver (this guide)** | Any Claude Code deployment | ✅ — telemetry is emitted client-side |

If the CLI is configured against AWS Bedrock or Google Vertex, **the OTLP path is the only option** — the Anthropic Console has no record of those requests.

---

## Architecture: Plan A (in-platform receiver) vs Plan B (OTel Collector)

### Plan A — direct-to-backend (what this repo implements)

```
Claude Code CLI ──OTLP/HTTP──► dora-backend  /api/v1/otel/v1/metrics ──► Postgres
```

- One pod. Backend speaks OTLP itself.
- Endpoint: `POST /api/v1/otel/v1/metrics`
- Auth: `X-API-Key: <DORA_API_KEY>` (same key as other mutating endpoints)
- Accepts both `application/x-protobuf` and `application/json`

**Use Plan A when:**

- You only need Claude Code metrics in this dashboard, nothing else
- You want minimum moving parts (single deployment, single log stream)
- You're on the trial setup or a small team

### Plan B — OTel Collector in front

```
Claude Code CLI ──OTLP──► OTel Collector ─┬─► dora-backend (same OTLP endpoint)
                                          ├─► Datadog / Grafana Cloud / Honeycomb
                                          └─► S3 archive / SIEM
```

- Two components: a Collector pod plus the backend.
- Collector handles batching, retries, multi-tenant routing, redaction, sampling, and **fan-out to multiple downstream systems** from a single pipeline.
- The backend keeps the same OTLP receiver — Plan B doesn't replace it, it just puts a smarter intake in front of it.

**Use Plan B when any of these apply:**

| Scenario | Why Plan B |
|----------|------------|
| You already operate an OTel Collector for app/infra telemetry | Add a `claude_code` pipeline; reuse existing auth, networking, alerting |
| Telemetry must reach two or more places (dashboard + Datadog, dashboard + audit S3) | Collector fan-out is one config block; coding the same in the backend means custom retry/backpressure logic |
| You need PII scrubbing before storage (e.g. strip `user.email` for compliance, derive a hash instead) | Collector has battle-tested `transform`/`attributes` processors; doing this inside the backend means schema changes |
| Volume is high enough that you want sampling, head-based or tail-based | Collector has dedicated samplers; the backend would have to bolt this on |
| You want cross-team multi-tenancy on the same intake (different teams, different downstreams) | Collector `routing` processor by `service.namespace` or resource attribute |
| Compliance requires the Collector image to be a vendored artefact, not a Python service | Collector is a Go binary with smaller surface area than a FastAPI app |

**Plan B sample collector config** (drop-in):

```yaml
# otel-collector-config.yaml
receivers:
  otlp:
    protocols:
      http:
        endpoint: 0.0.0.0:4318

processors:
  batch:
    timeout: 10s
    send_batch_size: 1000
  attributes/redact:
    actions:
      - key: user.email
        action: hash      # derive stable per-user hash, drop raw email
  filter/claude_code_only:
    metrics:
      include:
        match_type: regexp
        metric_names:
          - 'claude_code\..*'

exporters:
  otlphttp/dora:
    endpoint: https://dora-backend.example.com/api/v1/otel
    headers:
      x-api-key: ${env:DORA_API_KEY}
  # Add a second exporter to fan out to Datadog, Grafana, etc.
  # otlphttp/datadog:
  #   endpoint: https://api.datadoghq.com/api/v2/otlp
  #   headers:
  #     dd-api-key: ${env:DD_API_KEY}

service:
  pipelines:
    metrics:
      receivers: [otlp]
      processors: [filter/claude_code_only, attributes/redact, batch]
      exporters: [otlphttp/dora]
```

The backend doesn't change. Switching from Plan A to Plan B is operational, not architectural.

---

## Plan A: enabling Claude Code → backend

### 1. Confirm the receiver is up

```bash
# Inside the cluster (or with port-forward to the backend):
curl -s -o /dev/null -w "HTTP %{http_code}\n" \
  -H "X-API-Key: $DORA_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"resourceMetrics":[]}' \
  https://dora-backend.example.com/api/v1/otel/v1/metrics
# Expect 200 with body {"accepted_points":0,"rows_touched":0,"skipped_no_user":0}
```

A 401/403 means `X-API-Key` is wrong; a 415 means content-type isn't set; a 503 means `opentelemetry-proto` isn't installed in the running image.

### 2. Configure each engineer's environment

```bash
# Add to ~/.zshrc / ~/.bashrc (or push via dotfile management):
export CLAUDE_CODE_ENABLE_TELEMETRY=1
export OTEL_METRICS_EXPORTER=otlp
export OTEL_LOGS_EXPORTER=otlp
export OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
export OTEL_EXPORTER_OTLP_ENDPOINT=https://dora-backend.example.com/api/v1/otel
export OTEL_EXPORTER_OTLP_HEADERS=x-api-key=<DORA_API_KEY>
# Identify the user — required, otherwise points are dropped (skipped_no_user counter)
export OTEL_RESOURCE_ATTRIBUTES=user.email=$(git config user.email),service.name=claude-code
```

The receiver requires a `user.email` (or `user.id` / `enduser.id`) resource attribute. Points without it are counted under `skipped_no_user` in the response and dropped — this is intentional, because the dashboard aggregates per user.

### 3. Verify data is landing

After running `claude` for a session, check the DB:

```bash
kubectl -n dora-metrics exec deploy/postgres -- \
  psql -U dora -d dora_metrics -c \
  "SELECT user_email, session_date, num_sessions, lines_added, edit_accepted, edit_rejected FROM claude_code_sessions ORDER BY session_date DESC LIMIT 10;"
```

Then refresh the dashboard — the **Claude Code Analytics** panel should populate.

---

## Metric mapping

The receiver routes a fixed set of `claude_code.*` metric names into the existing `claude_code_sessions` table. Anything else is silently ignored (run a Collector if you need to capture more).

| OTel metric | Attributes used | DB column |
|-------------|-----------------|-----------|
| `claude_code.session.count` | — | `num_sessions` |
| `claude_code.lines_of_code.count` | `type=added` / `removed` | `lines_added` / `lines_removed` |
| `claude_code.commit.count` | — | `commits_created` |
| `claude_code.pull_request.count` | — | `prs_created` |
| `claude_code.code_edit_tool.decision` | `decision=accept` / `reject` | `edit_accepted` / `edit_rejected` |
| `claude_code.token.usage` | `type=input` / `output` | `tokens_input` / `tokens_output` |
| `claude_code.cost.usage` | — (USD) | `estimated_cost_cents` (×100) |

Aggregation key is `(user_email, session_date)` rounded to UTC midnight. Counters are **cumulative-max** — a row reflects the largest value seen for that day, so the CLI re-emitting the same cumulative point is idempotent.

---

## Threat model & operational notes

- **API key leak:** the `OTEL_EXPORTER_OTLP_HEADERS` env var ends up in every engineer's shell. Rotate `DORA_API_KEY` if a laptop is compromised.
- **Trust boundary:** the receiver trusts the `user.email` resource attribute to identify the user. Anyone with the API key can submit data attributed to anyone. Acceptable for internal team telemetry; **not** acceptable for billing or audit purposes.
- **Logs endpoint:** `/api/v1/otel/v1/logs` exists and returns 200 to keep the CLI from buffering, but discards content. If you want prompt/tool logs persisted, run Plan B and wire a separate exporter to a dedicated log store.
- **Body cap:** 4 MB per OTLP request. Larger batches will get a 413; the OTel SDK will retry with smaller batches.
