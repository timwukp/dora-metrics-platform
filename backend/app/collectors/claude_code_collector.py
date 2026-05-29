import httpx
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy.orm import Session
from app.config.settings import settings
from app.models.events import ClaudeCodeSession


class ClaudeCodeCollector:
    """Collects Claude Code analytics via the Admin API."""

    def __init__(self, admin_key: Optional[str] = None):
        self.admin_key = admin_key or settings.claude_code_admin_key
        self.base_url = settings.anthropic_api_base

    async def collect(self, db: Session, starting_at: str, ending_before: Optional[str] = None):
        if not self.admin_key:
            return

        async with httpx.AsyncClient() as client:
            cursor = None
            while True:
                params = {"starting_at": starting_at, "limit": 1000}
                if ending_before:
                    params["ending_before"] = ending_before
                if cursor:
                    params["cursor"] = cursor

                resp = await client.get(
                    f"{self.base_url}/v1/organizations/usage_report/claude_code",
                    headers={
                        "x-api-key": self.admin_key,
                        "anthropic-version": "2023-06-01",
                    },
                    params=params,
                )
                if resp.status_code != 200:
                    break

                data = resp.json()
                for record in data.get("data", []):
                    self._upsert_session(db, record)

                cursor = data.get("next_cursor")
                if not cursor or not data.get("has_more"):
                    break

            db.commit()

    def _upsert_session(self, db: Session, record: dict):
        actor = record.get("actor", {})
        email = actor.get("email_address") or actor.get("api_key_name", "unknown")
        session_date = _parse_dt(record["date"])

        existing = db.query(ClaudeCodeSession).filter(
            ClaudeCodeSession.user_email == email,
            ClaudeCodeSession.session_date == session_date,
        ).first()

        core = record.get("core_metrics", {})
        tools = record.get("tool_actions", {})
        models = record.get("model_usage", [])

        total_input = sum(m.get("tokens", {}).get("input", 0) for m in models)
        total_output = sum(m.get("tokens", {}).get("output", 0) for m in models)
        total_cost = sum(m.get("estimated_cost", {}).get("amount", 0) for m in models)
        primary_model = models[0].get("model", "") if models else ""

        edit_accepted = sum(
            tools.get(t, {}).get("accepted", 0)
            for t in ["edit_tool", "multi_edit_tool", "write_tool"]
        )
        edit_rejected = sum(
            tools.get(t, {}).get("rejected", 0)
            for t in ["edit_tool", "multi_edit_tool", "write_tool"]
        )

        loc = core.get("lines_of_code", {})
        values = dict(
            num_sessions=core.get("num_sessions", 0),
            lines_added=loc.get("added", 0),
            lines_removed=loc.get("removed", 0),
            commits_created=core.get("commits_by_claude_code", 0),
            prs_created=core.get("pull_requests_by_claude_code", 0),
            edit_accepted=edit_accepted,
            edit_rejected=edit_rejected,
            tokens_input=total_input,
            tokens_output=total_output,
            estimated_cost_cents=total_cost,
            model=primary_model,
        )

        if existing:
            for k, v in values.items():
                setattr(existing, k, v)
        else:
            db.add(ClaudeCodeSession(
                user_email=email,
                session_date=session_date,
                **values,
            ))


def _parse_dt(val) -> Optional[datetime]:
    if not val:
        return None
    return datetime.fromisoformat(val.replace("Z", "+00:00"))
