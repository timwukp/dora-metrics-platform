"""Sprint retro report rendering (issue #18).

Takes a DORA `summary()` dict and renders a self-contained Markdown report
suitable for pasting into Confluence / Notion / Slack. We intentionally do
NOT include charts or images here — Markdown is the lowest common
denominator and renders everywhere. PDF export is a future extension.

The "improvement suggestions" section is rule-based, not LLM-driven, so the
output is deterministic and audit-friendly. Each rule fires only when the
underlying signal is unambiguous (e.g. CFR > 15% AND >= 5 deployments) so
we never offer guidance from noise.
"""
from __future__ import annotations

from datetime import datetime, timezone


def _fmt_hours(h):
    if h is None:
        return "—"
    if h < 1:
        return f"{h * 60:.0f} min"
    if h < 24:
        return f"{h:.1f} h"
    return f"{h / 24:.1f} d"


def _fmt_pct(p):
    return "—" if p is None else f"{p:.1f}%"


def _suggestions(summary: dict) -> list[str]:
    out = []
    df = summary.get("deployment_frequency") or {}
    lt = summary.get("lead_time_for_changes") or {}
    cfr = summary.get("change_failure_rate") or {}
    mttr = summary.get("mean_time_to_recovery") or {}

    if df.get("effective_deploy_count", 0) >= 5 and df.get("deploys_per_day", 0) < 0.1:
        out.append(
            "Deployment frequency is below ~3/month with enough sample size "
            "to be a real signal. Consider whether the pipeline gates are "
            "the bottleneck (manual approvals, slow CI)."
        )

    coding = (lt.get("breakdown") or {}).get("coding_time_median_hours") or 0
    review = (lt.get("breakdown") or {}).get("review_time_median_hours") or 0
    if review > coding * 2 and (lt.get("sample_size") or 0) >= 3:
        out.append(
            "Review time dominates lead time (more than 2x coding time). "
            "Look at PR size and reviewer availability."
        )

    cfr_value = cfr.get("cfr_pct") if cfr.get("cfr_pct") is not None else cfr.get("combined_cfr_pct")
    if (cfr_value or 0) > 15 and (cfr.get("deployments") or cfr.get("total_merged_prs") or 0) >= 5:
        out.append(
            "Change failure rate exceeds 15%. Surface the top 3 failure root "
            "causes from the period and bring them to retro."
        )

    if (mttr.get("median_hours") or 0) > 24 and (mttr.get("sample_size") or 0) >= 2:
        out.append(
            "MTTR median is over 24h. Review on-call runbooks and alert "
            "routing — the time-to-detect is often the long pole."
        )

    if not out:
        out.append("No threshold rules fired this period. Discuss qualitative wins instead.")
    return out


def render_markdown(
    repo: str,
    summary: dict,
    *,
    sprint_label: str | None = None,
) -> str:
    """Render a Markdown retro report from a `DoraCalculator.summary()` dict."""
    df = summary.get("deployment_frequency") or {}
    lt = summary.get("lead_time_for_changes") or {}
    cfr = summary.get("change_failure_rate") or {}
    mttr = summary.get("mean_time_to_recovery") or {}
    period = df.get("period") or {}
    start = period.get("start", "")[:10]
    end = period.get("end", "")[:10]

    title = sprint_label or f"{start} → {end}"

    cfr_value = cfr.get("cfr_pct") if cfr.get("cfr_pct") is not None else cfr.get("combined_cfr_pct")

    lines: list[str] = []
    lines.append(f"# DORA Retro — {repo}")
    lines.append(f"**Period:** {title}  ({start} – {end})")
    lines.append("")
    lines.append("## Headline metrics")
    lines.append("")
    lines.append("| Metric | Value | DORA level |")
    lines.append("|---|---|---|")
    lines.append(
        f"| Deployment frequency | {df.get('deploys_per_day', '—')} deploys/day | "
        f"{df.get('dora_level', '—')} |"
    )
    lines.append(
        f"| Lead time (median)   | {_fmt_hours(lt.get('median_hours'))} | "
        f"{lt.get('dora_level', '—')} |"
    )
    lines.append(
        f"| Change failure rate  | {_fmt_pct(cfr_value)} | "
        f"{cfr.get('dora_level', '—')} |"
    )
    lines.append(
        f"| MTTR (median)        | {_fmt_hours(mttr.get('median_hours'))} | "
        f"{mttr.get('dora_level', '—')} |"
    )
    lines.append("")
    lines.append("## Breakdown")
    lines.append("")
    lines.append(f"- Effective deploys: **{df.get('effective_deploy_count', 0)}** "
                 f"(formal: {df.get('formal_deployments', 0)}, "
                 f"merged PRs proxy: {df.get('merged_prs', 0)})")
    breakdown = lt.get("breakdown") or {}
    lines.append(
        f"- Lead time split — coding: "
        f"{_fmt_hours(breakdown.get('coding_time_median_hours'))}, "
        f"review: {_fmt_hours(breakdown.get('review_time_median_hours'))}"
    )
    lines.append(
        f"- Failures: reverts={cfr.get('reverts', 0)}, "
        f"hotfixes={cfr.get('hotfixes', 0)}, incidents={cfr.get('incidents', 0)}"
    )
    if mttr.get("sample_size") is not None:
        lines.append(
            f"- Recovery sample: {mttr.get('sample_size', 0)} events "
            f"(P95 {_fmt_hours(mttr.get('p95_hours'))})"
        )
    lines.append("")
    lines.append("## Suggested discussion topics")
    lines.append("")
    for s in _suggestions(summary):
        lines.append(f"- {s}")
    lines.append("")
    lines.append("---")
    lines.append(
        f"_Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} "
        f"by DORA Metrics Platform_"
    )
    return "\n".join(lines) + "\n"
