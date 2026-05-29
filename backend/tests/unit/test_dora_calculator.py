"""End-to-end formula coverage for DoraCalculator using SQLite.

These tests exist because the previous implementation:
  - measured Lead Time ending at merge (ignoring deploy time);
  - lumped CFR with CI failure rate (which inflated it);
  - filtered deployments by status only, accepting non-prod environments.

Each test here pins the *correct* behaviour for one of those.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models.events import Deployment, Incident, PullRequest
from app.services.dora_calculator import DoraCalculator


def _utc(year, month, day, hour=0):
    return datetime(year, month, day, hour, tzinfo=timezone.utc)


def test_lead_time_includes_deploy(db_session):
    """A PR merged Mon, deployed Wed → Lead Time spans Sun (first commit) to Wed."""
    pr = PullRequest(
        repo="octo/repo", number=1, title="feat",
        author="dev", state="merged",
        first_commit_at=_utc(2026, 1, 4),  # Sun
        created_at=_utc(2026, 1, 4),
        merged_at=_utc(2026, 1, 5),        # Mon
    )
    deploy = Deployment(
        repo="octo/repo", environment="production", sha="abc",
        deployed_at=_utc(2026, 1, 7),      # Wed
        status="success",
    )
    db_session.add_all([pr, deploy])
    db_session.commit()

    out = DoraCalculator(db_session, repo="octo/repo").lead_time_for_changes(
        _utc(2026, 1, 1), _utc(2026, 1, 31),
    )
    # Sunday → Wednesday = 72 hours
    assert out["sample_size"] == 1
    assert out["median_hours"] == 72.0
    assert out["deploy_linked"] == 1
    assert out["merge_fallback"] == 0


def test_lead_time_falls_back_to_merge_when_no_deploy(db_session):
    pr = PullRequest(
        repo="octo/repo", number=2, title="feat",
        author="dev", state="merged",
        first_commit_at=_utc(2026, 1, 5),
        created_at=_utc(2026, 1, 5),
        merged_at=_utc(2026, 1, 5, hour=12),
    )
    db_session.add(pr)
    db_session.commit()

    out = DoraCalculator(db_session, repo="octo/repo").lead_time_for_changes(
        _utc(2026, 1, 1), _utc(2026, 1, 31),
    )
    assert out["sample_size"] == 1
    assert out["median_hours"] == 12.0
    assert out["deploy_linked"] == 0
    assert out["merge_fallback"] == 1


def test_cfr_uses_deployments_not_ci(db_session):
    """3 deploys, 1 hotfix → CFR = 33.3% even if CI failed every run."""
    db_session.add_all([
        Deployment(
            repo="octo/repo", environment="production", sha=f"sha{i}",
            deployed_at=_utc(2026, 1, 5 + i), status="success",
        )
        for i in range(3)
    ])
    db_session.add(PullRequest(
        repo="octo/repo", number=1, title="hotfix: pager",
        author="dev", state="merged",
        merged_at=_utc(2026, 1, 6), is_hotfix=True,
    ))
    db_session.commit()

    out = DoraCalculator(db_session, repo="octo/repo").change_failure_rate(
        _utc(2026, 1, 1), _utc(2026, 1, 31),
    )
    assert out["deployments"] == 3
    assert out["failures"] == 1
    assert out["cfr_pct"] == round(1 / 3 * 100, 2)
    assert out["source"] == "deployments"


def test_prod_filter_excludes_staging_deploys(db_session):
    db_session.add_all([
        Deployment(
            repo="octo/repo", environment="staging", sha="s1",
            deployed_at=_utc(2026, 1, 5), status="success",
        ),
        Deployment(
            repo="octo/repo", environment="production", sha="p1",
            deployed_at=_utc(2026, 1, 5), status="success",
        ),
    ])
    db_session.commit()

    out = DoraCalculator(db_session, repo="octo/repo").deployment_frequency(
        _utc(2026, 1, 1), _utc(2026, 1, 31),
    )
    assert out["formal_deployments"] == 1


def test_mttr_combines_incidents_and_hotfixes(db_session):
    db_session.add(Incident(
        repo="octo/repo", started_at=_utc(2026, 1, 5),
        resolved_at=_utc(2026, 1, 5, hour=2),
        title="pager",
    ))
    db_session.add(PullRequest(
        repo="octo/repo", number=10, title="hotfix: data loss",
        author="dev", state="merged", is_hotfix=True,
        created_at=_utc(2026, 1, 6), merged_at=_utc(2026, 1, 6, hour=4),
    ))
    db_session.commit()

    out = DoraCalculator(db_session, repo="octo/repo").mean_time_to_recovery(
        _utc(2026, 1, 1), _utc(2026, 1, 31),
    )
    assert out["sample_size"] == 2
    assert out["from_incidents"] == 1
    assert out["from_hotfix_prs"] == 1
    assert out["median_hours"] == 3.0  # median of 2h and 4h
