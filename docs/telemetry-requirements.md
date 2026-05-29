# Telemetry Requirements for DORA Metrics

## Complete Data Source Matrix

### 1. Deployment Frequency

| Data Point | Source | API/Method | Your Repo Status |
|------------|--------|-----------|-----------------|
| Production deployments | GitHub Deployments API | `GET /repos/{owner}/{repo}/deployments` | No formal deploys configured |
| Merged PRs (proxy) | GitHub Pull Requests | `GET /repos/{owner}/{repo}/pulls?state=closed` | 5 merged PRs available |
| Successful CI on main | GitHub Actions | `GET /repos/{owner}/{repo}/actions/runs` | Active - PII scan, Secret Scanning, etc. |
| Claude Code PRs | Claude Code Analytics API | `GET /v1/organizations/usage_report/claude_code` | Requires admin key |

### 2. Lead Time for Changes

| Data Point | Source | API/Method | Your Repo Status |
|------------|--------|-----------|-----------------|
| First commit timestamp | GitHub PR Commits | `GET /repos/{owner}/{repo}/pulls/{pr}/commits` | Available for all PRs |
| PR created timestamp | GitHub PR | `pull_request.created_at` | Available |
| First review timestamp | GitHub Reviews | `GET /repos/{owner}/{repo}/pulls/{pr}/reviews` | Bot reviews within 1-2 min |
| Approved timestamp | GitHub Reviews | `review.state == "APPROVED"` | **No human approvals found** |
| Merged timestamp | GitHub PR | `pull_request.merged_at` | Available for 5 PRs |
| Deploy timestamp | GitHub Deployments | `deployment.created_at` | Not configured |

### 3. Change Failure Rate

| Data Point | Source | API/Method | Your Repo Status |
|------------|--------|-----------|-----------------|
| Failed CI runs on main | GitHub Actions | `workflow_run.conclusion == "failure"` | 3 failures found (SBOM) |
| Total CI runs on main | GitHub Actions | All push-event runs on main | Active |
| Revert PRs | GitHub PR title | `title LIKE "Revert%"` | 0 reverts |
| Hotfix PRs | GitHub PR title/branch | `title/branch LIKE "%fix%"` | PR #7 is a fix |
| Production incidents | PagerDuty/OpsGenie API | Incident start/resolve times | Not integrated |

### 4. Mean Time to Recovery

| Data Point | Source | API/Method | Your Repo Status |
|------------|--------|-----------|-----------------|
| Incident start time | Incident Management | PagerDuty/OpsGenie webhook | Not integrated |
| Incident resolve time | Incident Management | Status change to "resolved" | Not integrated |
| Hotfix PR created→merged | GitHub PR | `merged_at - created_at` for hotfix PRs | PR #7: 5 min |
| Recovery deploy time | GitHub Deployments | Next successful deploy after failure | Not configured |

### 5. Claude Code Telemetry

| Data Point | Source | Collection Method |
|------------|--------|-------------------|
| Sessions per user per day | Analytics API | `core_metrics.num_sessions` |
| Lines added/removed | Analytics API | `core_metrics.lines_of_code` |
| Commits by Claude Code | Analytics API | `core_metrics.commits_by_claude_code` |
| PRs by Claude Code | Analytics API | `core_metrics.pull_requests_by_claude_code` |
| Edit tool accept/reject | Analytics API | `tool_actions.edit_tool.accepted/rejected` |
| Token usage per model | Analytics API | `model_usage[].tokens` |
| Cost per developer | Analytics API | `model_usage[].estimated_cost` |
| Real-time session events | OpenTelemetry | `claude_code.session.count` metric |
| Real-time code edits | OpenTelemetry | `claude_code.code_edit_tool.decision` event |
| Active time | OpenTelemetry | `claude_code.active_time.total` metric |

### 6. PR Review & Approval Telemetry (from your repo)

| Data Point | Source | Findings |
|------------|--------|----------|
| Review comments | GitHub Reviews API | `amazon-q-developer[bot]` COMMENTED on all PRs |
| Human approvals | GitHub Reviews API | **None found** - all self-merged |
| Review latency | Reviews `submitted_at` - PR `created_at` | Bot: ~40 seconds avg |
| Review coverage | Reviews / Total PRs | 100% (all reviewed by bot) |

## GitHub Webhook Events to Configure

For real-time data ingestion, configure these webhook events on your repo:

```
Settings → Webhooks → Add webhook
URL: https://your-dora-platform.com/api/v1/webhooks/github
Content type: application/json
Events:
  ✓ Pull requests (opened, closed, merged, review_requested)
  ✓ Pull request reviews (submitted, approved, changes_requested)
  ✓ Workflow runs (completed)
  ✓ Deployments (created)
  ✓ Deployment statuses (updated)
  ✓ Push (to track commits)
```

## Missing Data for Full DORA Coverage

Based on analysis of `timwukp/agentic-ai-industry-use-cases`:

1. **No formal GitHub Deployments** - Using merged-to-main as proxy
2. **No human PR approvals** - All PRs self-merged after bot review
3. **No incident management integration** - Need PagerDuty/OpsGenie for MTTR
4. **No production environment defined** - All CI runs, no deploy pipeline
5. **Claude Code Admin API key** - Needed for AI contribution metrics

## Recommendations

1. Configure GitHub Environments (production) and require PR approval
2. Set up GitHub Deployment API calls in your CI/CD workflows
3. Add an incident management tool (even a simple GitHub Issues label)
4. Enable Claude Code telemetry via `CLAUDE_CODE_ENABLE_TELEMETRY=1`
5. Set up the OTel collector to receive real-time Claude Code events
