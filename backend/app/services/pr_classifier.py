"""Classify a GitHub PR as revert / hotfix.

We deliberately avoid loose substring matches (e.g. "fix" in branch). The
classifier only returns true on patterns that are conventionally used for
production hotfixes / reverts, plus an explicit label override.
"""
from __future__ import annotations

import re
from typing import Iterable

# Branch / title patterns. Anchored — no `feat/fix-tooltip` false positives.
_HOTFIX_BRANCH_RE = re.compile(r"^(hotfix|patch)([/_\-]|$)", re.IGNORECASE)
_HOTFIX_TITLE_RE = re.compile(r"^(hotfix\b|\[hotfix\])", re.IGNORECASE)
_REVERT_TITLE_RE = re.compile(r"^revert\b", re.IGNORECASE)


def is_revert(title: str | None, labels: Iterable[str] | None = None) -> bool:
    if labels and any((label or "").lower() == "revert" for label in labels):
        return True
    if not title:
        return False
    return bool(_REVERT_TITLE_RE.match(title.strip()))


def is_hotfix(
    title: str | None,
    branch: str | None,
    labels: Iterable[str] | None = None,
) -> bool:
    if labels and any((label or "").lower() in {"hotfix", "incident"} for label in labels):
        return True
    if title and _HOTFIX_TITLE_RE.match(title.strip()):
        return True
    if branch and _HOTFIX_BRANCH_RE.match(branch.strip()):
        return True
    return False


_AI_PATTERNS = {
    "claude-code": re.compile(r"\b(co-authored-by:\s*claude|claude-code)\b", re.IGNORECASE),
    "copilot":     re.compile(r"\b(co-authored-by:\s*copilot|github-copilot)\b", re.IGNORECASE),
    "amazon-q":    re.compile(r"\bamazon-q\b", re.IGNORECASE),
}


def detect_ai_assistant(body: str | None) -> str | None:
    """Look for explicit 'Co-authored-by:' trailers or specific tool tags.

    Substring matches like 'claude' in body are too loose — a PR that just
    *mentions* Claude shouldn't be tagged. We require a Co-authored-by trailer
    (which the tools actually emit) or a labelled mention.
    """
    if not body:
        return None
    for tool, pat in _AI_PATTERNS.items():
        if pat.search(body):
            return tool
    return None
