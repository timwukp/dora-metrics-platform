from sqlalchemy import (
    Column, Integer, BigInteger, String, DateTime, Float, Boolean, Text, JSON,
    UniqueConstraint, Index,
)
from sqlalchemy.sql import func
from app.models.database import Base


class Deployment(Base):
    __tablename__ = "deployments"
    __table_args__ = (
        UniqueConstraint("repo", "sha", "environment", name="uq_deployment_sha_env"),
        Index("ix_deploy_repo_deployed_at", "repo", "deployed_at"),
        Index("ix_deploy_status_env", "status", "environment"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    repo = Column(String(255), nullable=False, index=True)
    environment = Column(String(50), default="production")
    sha = Column(String(40))
    ref = Column(String(255))
    deployed_at = Column(DateTime(timezone=True), nullable=False)
    status = Column(String(20), nullable=False)  # success, failure, rollback
    triggered_by = Column(String(100))
    duration_seconds = Column(Float)
    pr_number = Column(Integer)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class PullRequest(Base):
    __tablename__ = "pull_requests"
    __table_args__ = (
        UniqueConstraint("repo", "number", name="uq_pr_repo_number"),
        Index("ix_pr_repo_merged_at", "repo", "merged_at"),
        Index("ix_pr_repo_first_commit_at", "repo", "first_commit_at"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    repo = Column(String(255), nullable=False, index=True)
    number = Column(Integer, nullable=False)
    title = Column(Text)
    state = Column(String(20))  # open, closed, merged
    author = Column(String(100))
    created_at = Column(DateTime(timezone=True))
    merged_at = Column(DateTime(timezone=True))
    closed_at = Column(DateTime(timezone=True))
    first_commit_at = Column(DateTime(timezone=True))
    review_requested_at = Column(DateTime(timezone=True))
    first_review_at = Column(DateTime(timezone=True))
    approved_at = Column(DateTime(timezone=True))
    additions = Column(Integer, default=0)
    deletions = Column(Integer, default=0)
    changed_files = Column(Integer, default=0)
    is_revert = Column(Boolean, default=False)
    is_hotfix = Column(Boolean, default=False)
    labels = Column(JSON, default=list)
    assisted_by = Column(String(100))  # claude-code, amazon-q, copilot, etc.


class Commit(Base):
    __tablename__ = "commits"
    __table_args__ = (
        Index("ix_commit_repo_authored_at", "repo", "authored_at"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    repo = Column(String(255), nullable=False, index=True)
    sha = Column(String(40), nullable=False, unique=True)
    message = Column(Text)
    author = Column(String(100))
    authored_at = Column(DateTime(timezone=True))
    pr_number = Column(Integer)
    is_merge = Column(Boolean, default=False)


class WorkflowRun(Base):
    __tablename__ = "workflow_runs"
    __table_args__ = (
        Index("ix_wfr_repo_branch_event_started", "repo", "head_branch", "event", "started_at"),
        Index("ix_wfr_repo_started_at", "repo", "started_at"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    repo = Column(String(255), nullable=False, index=True)
    run_id = Column(BigInteger, nullable=False, unique=True)
    name = Column(String(255))
    conclusion = Column(String(20))  # success, failure, cancelled
    event = Column(String(50))  # push, pull_request
    head_branch = Column(String(255))
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    duration_seconds = Column(Float)


class Incident(Base):
    __tablename__ = "incidents"
    __table_args__ = (
        Index("ix_incident_repo_started_at", "repo", "started_at"),
        Index("ix_incident_resolved_at", "resolved_at"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    repo = Column(String(255), index=True)
    external_id = Column(String(100))
    title = Column(Text)
    severity = Column(String(20))  # critical, high, medium, low
    started_at = Column(DateTime(timezone=True), nullable=False)
    resolved_at = Column(DateTime(timezone=True))
    recovery_commit_sha = Column(String(40))
    caused_by_deployment_id = Column(BigInteger)
    source = Column(String(50))  # pagerduty, opsgenie, manual


class ClaudeCodeSession(Base):
    __tablename__ = "claude_code_sessions"
    __table_args__ = (
        UniqueConstraint("user_email", "session_date", name="uq_ccs_user_date"),
        Index("ix_ccs_session_date", "session_date"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_email = Column(String(255), index=True)
    session_date = Column(DateTime(timezone=True))
    num_sessions = Column(Integer, default=0)
    lines_added = Column(Integer, default=0)
    lines_removed = Column(Integer, default=0)
    commits_created = Column(Integer, default=0)
    prs_created = Column(Integer, default=0)
    edit_accepted = Column(Integer, default=0)
    edit_rejected = Column(Integer, default=0)
    tokens_input = Column(BigInteger, default=0)
    tokens_output = Column(BigInteger, default=0)
    estimated_cost_cents = Column(Float, default=0.0)
    model = Column(String(100))


class ReviewEvent(Base):
    __tablename__ = "review_events"
    __table_args__ = (
        Index("ix_review_repo_submitted_at", "repo", "submitted_at"),
        Index("ix_review_repo_pr_reviewer_submitted", "repo", "pr_number", "reviewer", "submitted_at"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    repo = Column(String(255), nullable=False, index=True)
    pr_number = Column(Integer, nullable=False)
    reviewer = Column(String(100))
    state = Column(String(30))  # APPROVED, CHANGES_REQUESTED, COMMENTED
    submitted_at = Column(DateTime(timezone=True))
    is_bot = Column(Boolean, default=False)


class OtelCumulativeState(Base):
    """High-water mark for OTLP cumulative counters, per (user, day, metric+attrs).

    Used to convert cumulative observations into deltas before applying them to
    claude_code_sessions. See app.api.otel_receiver._resolve_increment.
    """
    __tablename__ = "otel_cumulative_state"
    __table_args__ = (
        UniqueConstraint("user_email", "session_date", "metric_key",
                         name="uq_otel_cum_state"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_email = Column(String(255), nullable=False)
    session_date = Column(DateTime(timezone=True), nullable=False)
    metric_key = Column(String(512), nullable=False)
    last_value = Column(Float, default=0.0)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(),
                        onupdate=func.now())


class WebhookDelivery(Base):
    """Replay-protection table for inbound webhooks. We record each delivery
    id once; duplicates are rejected with a 200 no-op (so the sender doesn't
    retry forever)."""
    __tablename__ = "webhook_deliveries"
    __table_args__ = (
        UniqueConstraint("source", "delivery_id", name="uq_webhook_source_delivery"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    source = Column(String(50), nullable=False)  # github, etc.
    delivery_id = Column(String(128), nullable=False)
    received_at = Column(DateTime(timezone=True), server_default=func.now())
