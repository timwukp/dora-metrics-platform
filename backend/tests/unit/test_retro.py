"""Sprint retro Markdown renderer (issue #18)."""
from __future__ import annotations

from app.services.retro import render_markdown


_BASE_SUMMARY = {
    "deployment_frequency": {
        "period": {"start": "2026-04-01T00:00:00Z", "end": "2026-04-15T00:00:00Z"},
        "deploys_per_day": 0.4,
        "effective_deploy_count": 6,
        "formal_deployments": 0,
        "merged_prs": 6,
        "dora_level": "High",
    },
    "lead_time_for_changes": {
        "median_hours": 2.5,
        "p95_hours": 18.0,
        "sample_size": 6,
        "breakdown": {"coding_time_median_hours": 0.5, "review_time_median_hours": 2.0},
        "dora_level": "Elite",
    },
    "change_failure_rate": {
        "cfr_pct": 0.0,
        "deployments": 0,
        "total_merged_prs": 6,
        "reverts": 0,
        "hotfixes": 0,
        "incidents": 0,
        "dora_level": "Elite",
    },
    "mean_time_to_recovery": {
        "median_hours": None,
        "p95_hours": None,
        "sample_size": 0,
        "from_incidents": 0,
        "from_hotfix_prs": 0,
        "dora_level": "—",
    },
}


def test_renders_required_sections():
    md = render_markdown("octo/repo", _BASE_SUMMARY, sprint_label="Sprint 7")
    assert "# DORA Retro — octo/repo" in md
    assert "Sprint 7" in md
    assert "## Headline metrics" in md
    assert "## Breakdown" in md
    assert "## Suggested discussion topics" in md
    # Period appears inline
    assert "2026-04-01" in md and "2026-04-15" in md
    # Trailing newline so it concatenates cleanly
    assert md.endswith("\n")


def test_suggestions_fire_on_high_cfr():
    summary = dict(_BASE_SUMMARY)
    summary["change_failure_rate"] = {
        **_BASE_SUMMARY["change_failure_rate"],
        "cfr_pct": 25.0,
        "deployments": 8,
    }
    md = render_markdown("octo/repo", summary)
    assert "Change failure rate exceeds 15%" in md


def test_suggestions_fire_when_review_dominates_lead_time():
    summary = dict(_BASE_SUMMARY)
    summary["lead_time_for_changes"] = {
        **_BASE_SUMMARY["lead_time_for_changes"],
        "breakdown": {"coding_time_median_hours": 1.0, "review_time_median_hours": 10.0},
        "sample_size": 5,
    }
    md = render_markdown("octo/repo", summary)
    assert "Review time dominates lead time" in md


def test_suggestions_fallback_when_no_rules_fire():
    # Tighten the baseline so no individual rule fires: balanced lead time
    # split, low CFR, low MTTR, healthy deploy cadence.
    summary = {
        "deployment_frequency": {
            "period": {"start": "2026-04-01T00:00:00Z", "end": "2026-04-15T00:00:00Z"},
            "deploys_per_day": 1.0,
            "effective_deploy_count": 14,
            "formal_deployments": 14,
            "merged_prs": 14,
            "dora_level": "Elite",
        },
        "lead_time_for_changes": {
            "median_hours": 1.0,
            "sample_size": 5,
            "breakdown": {
                "coding_time_median_hours": 1.0,
                "review_time_median_hours": 1.0,
            },
            "dora_level": "Elite",
        },
        "change_failure_rate": {
            "cfr_pct": 5.0,
            "deployments": 14,
            "reverts": 0, "hotfixes": 0, "incidents": 0,
            "dora_level": "Elite",
        },
        "mean_time_to_recovery": {
            "median_hours": 0.5,
            "sample_size": 1,
            "from_incidents": 1, "from_hotfix_prs": 0,
            "dora_level": "Elite",
        },
    }
    md = render_markdown("octo/repo", summary)
    assert "No threshold rules fired" in md


def test_handles_missing_breakdown_keys():
    summary = {
        "deployment_frequency": {
            "period": {"start": "2026-01-01T00:00:00Z", "end": "2026-01-08T00:00:00Z"},
        },
        "lead_time_for_changes": {},
        "change_failure_rate": {},
        "mean_time_to_recovery": {},
    }
    # Should not raise
    md = render_markdown("octo/repo", summary)
    assert "# DORA Retro — octo/repo" in md
