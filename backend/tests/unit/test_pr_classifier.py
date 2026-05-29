"""Make sure the classifier doesn't return false positives on innocent PRs."""
from app.services.pr_classifier import detect_ai_assistant, is_hotfix, is_revert


def test_revert_anchored_to_title_start():
    assert is_revert('Revert "feat: thing"') is True
    # `fix: revert button` mentions revert but is not a revert
    assert is_revert("fix: revert button label") is False


def test_revert_label_override():
    assert is_revert("anything", labels=["revert"]) is True


def test_hotfix_branch_is_anchored():
    assert is_hotfix(None, "hotfix/foo") is True
    assert is_hotfix(None, "hotfix-bar") is True
    # Old loose match flagged everything containing "fix" — verify it doesn't
    # any more.
    assert is_hotfix(None, "feat/fix-tooltip") is False
    assert is_hotfix(None, "release/2024-q1") is False


def test_hotfix_title_anchored():
    assert is_hotfix("hotfix: pager fired", None) is True
    assert is_hotfix("[hotfix] revert ABC", None) is True
    assert is_hotfix("nothotfix really", None) is False


def test_ai_assistant_requires_strong_signal():
    # Mentioning "claude" inline is not enough — old code tagged half the
    # repo as Claude-assisted because reviewers wrote "Claude says…".
    assert detect_ai_assistant("Claude is great in general") is None
    assert detect_ai_assistant(
        "Co-authored-by: Claude <noreply@anthropic.com>"
    ) == "claude-code"
    assert detect_ai_assistant(
        "Co-authored-by: Copilot <copilot@github.com>"
    ) == "copilot"
