# Secret Rotation Runbook (trial mode)

Manual procedures. No automation; trial mode keeps the blast radius small and
the moving parts visible. Each section is self-contained: stop, rotate,
verify.

Trial-mode boundaries:
- Secrets live in the `dora-secrets` Kubernetes Secret in namespace
  `dora-metrics`. No AWS Secrets Manager.
- No HA: rotation involves a brief restart for the deployment that consumes
  the secret. Acceptable for trial; not acceptable for prod.

Prereqs: `kubectl` context set to `dora-trial`, `gh` authenticated for the
`timwukp/dora-metrics-platform` repo.

---

## 1. OTEL ingestion API key (`DORA_API_KEY`)

Used by the Claude Code CLI / OTel collectors to authenticate to
`/api/v1/otel/v1/*`. Local copy lives at `~/.config/dora/apikey` (chmod 600).

```sh
NEW=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')
umask 077
echo -n "$NEW" > ~/.config/dora/apikey

kubectl -n dora-metrics patch secret dora-secrets --type=json \
  -p "[{\"op\":\"replace\",\"path\":\"/data/DORA_API_KEY\",\"value\":\"$(printf '%s' "$NEW" | base64)\"}]"

kubectl -n dora-metrics rollout restart deploy/dora-backend
kubectl -n dora-metrics rollout status deploy/dora-backend --timeout=90s
```

Verify (port-forward must be up):

```sh
curl -s -o /dev/null -w '%{http_code}\n' \
  -H "X-API-Key: $(cat ~/.config/dora/apikey)" \
  -X POST -H 'Content-Type: application/json' \
  --data '{"resourceMetrics":[]}' \
  http://localhost:8000/api/v1/otel/v1/metrics
# expect 200
```

Update any external CLI/collector configs that hold the old key.

---

## 2. GitHub webhook secret (`DORA_GITHUB_WEBHOOK_SECRET`)

Validates HMAC on inbound webhooks at `/api/v1/webhooks/github`. Must match
the value configured in each GitHub repo's webhook settings.

```sh
NEW=$(python3 -c 'import secrets; print(secrets.token_hex(32))')

kubectl -n dora-metrics patch secret dora-secrets --type=json \
  -p "[{\"op\":\"replace\",\"path\":\"/data/DORA_GITHUB_WEBHOOK_SECRET\",\"value\":\"$(printf '%s' "$NEW" | base64)\"}]"

kubectl -n dora-metrics rollout restart deploy/dora-backend
```

Then update each repo webhook's `Secret` field in
`Settings → Webhooks → <hook> → Edit`. Webhooks signed with the old secret
will be rejected (401) once the backend restart completes — the gap is the
restart window (≈30s).

Verify by re-delivering a webhook from the GitHub UI ("Recent Deliveries
→ Redeliver") and checking backend logs:

```sh
kubectl -n dora-metrics logs deploy/dora-backend --tail=20 | grep webhook
```

---

## 3. GitHub PAT (`DORA_GITHUB_TOKEN`)

Used by the collector to read PRs, commits, and CI runs. Trial mode uses a
fine-grained personal access token.

1. In GitHub, generate a new fine-grained PAT scoped to the same repos with
   `Contents: Read`, `Pull requests: Read`, `Metadata: Read`. Note the value.
2. Patch the secret:

```sh
NEW='<paste-new-pat>'
kubectl -n dora-metrics patch secret dora-secrets --type=json \
  -p "[{\"op\":\"replace\",\"path\":\"/data/DORA_GITHUB_TOKEN\",\"value\":\"$(printf '%s' "$NEW" | base64)\"}]"

kubectl -n dora-metrics rollout restart deploy/dora-backend
unset NEW
```

3. Verify the next collection cycle succeeds:

```sh
kubectl -n dora-metrics logs deploy/dora-backend --tail=200 | grep "GitHub collection"
# expect "GitHub collection completed" without auth errors
```

4. Revoke the old PAT in GitHub settings only after one successful collection
   cycle on the new token.

Never paste the PAT into chat, commits, or shell history files. After the
above, run `history -d $(history | tail -2 | head -1 | awk '{print $1}')`
or restart the shell.

---

## 4. Postgres password (`POSTGRES_PASSWORD`)

Trial mode runs Postgres as a pod with `emptyDir` storage — restarting the
pod wipes the database (data is repopulated by the next collection cycle).
Rotating the password therefore takes the platform down for ~1 minute and
then re-collects from GitHub.

```sh
NEW=$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')

# Update both POSTGRES_PASSWORD and the password embedded in DORA_DATABASE_URL.
NEW_URL="postgresql+psycopg2://dora:${NEW}@postgres:5432/dora"

kubectl -n dora-metrics patch secret dora-secrets --type=json -p "[
  {\"op\":\"replace\",\"path\":\"/data/POSTGRES_PASSWORD\",\"value\":\"$(printf '%s' "$NEW" | base64)\"},
  {\"op\":\"replace\",\"path\":\"/data/DORA_DATABASE_URL\",\"value\":\"$(printf '%s' "$NEW_URL" | base64)\"}
]"

kubectl -n dora-metrics rollout restart deploy/postgres
kubectl -n dora-metrics rollout status deploy/postgres --timeout=90s
kubectl -n dora-metrics rollout restart deploy/dora-backend
kubectl -n dora-metrics rollout status deploy/dora-backend --timeout=90s
```

Verify:

```sh
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8000/api/v1/health/ready
# expect 200; allow 1–2 min for the next collection cycle to repopulate metrics
```

---

## Audit trail

After any rotation, append a one-line entry here (manual log; future work to
ship structured rotation events to CloudTrail via Secrets Manager once we
exit trial mode):

```
YYYY-MM-DD <secret-name> rotated by <who> — reason: <scheduled|incident|departure>
```

| Date       | Secret                          | Operator | Reason     |
|------------|---------------------------------|----------|------------|
| 2026-05-30 | (initial deployment, no rotation yet) | tmwu | n/a   |

---

## When trial graduates to prod

These manual procedures should be replaced with:

- AWS Secrets Manager + `external-secrets` operator (manifest already drafted
  at `infra/k8s/external-secrets.yaml`); the IRSA role `dora-backend-irsa` is
  already attached to the `dora-backend` ServiceAccount and is ready to
  receive a `secretsmanager:GetSecretValue` policy.
- Postgres on RDS with IAM auth — eliminates the static password rotation
  entirely.
- EKS secrets KMS envelope encryption — currently `encryptionConfig: null` on
  `dora-trial`. Cannot be enabled in place; requires cluster recreation.
