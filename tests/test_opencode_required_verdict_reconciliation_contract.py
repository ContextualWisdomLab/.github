"""Executable regressions for event-driven OpenCode verdict reconciliation."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import textwrap

from scripts.ci import opencode_review_receipt_gate

SCHEDULER = Path(".github/workflows/pr-review-merge-scheduler.yml")
OPENCODE = Path(".github/workflows/opencode-review.yml")
HEAD = "a" * 40


def _scheduler_jq_filter() -> str:
    """Extract the production scheduler review selector."""
    text = SCHEDULER.read_text(encoding="utf-8")
    anchor = text.index('latest_review="$(printf')
    start = text.index("            (add // [])", anchor)
    end_marker = "            | @tsv"
    end = text.index(end_marker, start) + len(end_marker)
    return textwrap.dedent(text[start:end])


def _admission_jq_filter() -> str:
    """Extract the production one-shot admission review selector."""
    text = OPENCODE.read_text(encoding="utf-8")
    anchor = text.index('verdict="$(printf')
    start = text.index("            (add // [])", anchor)
    end_marker = '              then "APPROVED" else empty end'
    end = text.index(end_marker, start) + len(end_marker)
    return textwrap.dedent(text[start:end])


def _run_filter(filter_text: str, reviews: list[dict[str, object]]) -> str:
    """Execute one production jq selector against exact-head fixtures."""
    proc = subprocess.run(
        ["jq", "-r", "-s", "--arg", "sha", HEAD, filter_text],
        input=json.dumps(reviews),
        text=True,
        capture_output=True,
        check=True,
    )
    return proc.stdout.strip()


def _scheduler_select(reviews: list[dict[str, object]]) -> str:
    """Execute the scheduler selector."""
    return _run_filter(_scheduler_jq_filter(), reviews)


def _admission_select(reviews: list[dict[str, object]]) -> str:
    """Execute the one-shot admission selector."""
    return _run_filter(_admission_jq_filter(), reviews)


def _review(
    state: str,
    body: str,
    *,
    login: str = "opencode-agent[bot]",
) -> dict[str, object]:
    """Build one exact-head formal-review fixture."""
    return {
        "id": 42,
        "user": {"login": login},
        "commit_id": HEAD,
        "state": state,
        "body": f"## Verdict\n{body}\n\nHead SHA: `{HEAD}`",
        "submitted_at": "2026-09-02T12:00:00Z",
    }


def test_marker_bearing_change_request_remains_a_formal_verdict() -> None:
    """Fallback markers invalidate approvals only, never a real change request."""
    review = _review("CHANGES_REQUESTED", "deterministic fallback approval: defect remains")
    assert _scheduler_select([review]).startswith("CHANGES_REQUESTED\t")
    assert _admission_select([review]) == "CHANGES_REQUESTED"
    assert opencode_review_receipt_gate.is_formal_receipt(
        review, HEAD, is_draft=False
    )[0]


def test_marker_bearing_approval_is_not_admitted() -> None:
    """Synthetic/fallback approval markers still block APPROVED evidence."""
    review = _review("APPROVED", "deterministic fallback approval")
    assert _scheduler_select([review]) == ""
    assert _admission_select([review]) == ""
    assert not opencode_review_receipt_gate.is_formal_receipt(
        review, HEAD, is_draft=False
    )[0]


def test_clean_approval_is_admitted() -> None:
    """A clean exact-head approval remains a formal verdict everywhere."""
    review = _review("APPROVED", "real model review")
    assert _scheduler_select([review]).startswith("APPROVED\t")
    assert _admission_select([review]) == "APPROVED"
    assert opencode_review_receipt_gate.is_formal_receipt(
        review, HEAD, is_draft=False
    )[0]


def test_github_actions_formal_receipt_reconciles_and_admits() -> None:
    """Every accepted formal publisher must be accepted by all verdict gates."""
    review = _review(
        "CHANGES_REQUESTED",
        "current-head defect remains",
        login="github-actions[bot]",
    )
    assert _scheduler_select([review]).startswith("CHANGES_REQUESTED\t")
    assert _admission_select([review]) == "CHANGES_REQUESTED"
    assert opencode_review_receipt_gate.is_formal_receipt(
        review, HEAD, is_draft=False
    )[0]


def test_same_second_review_is_eligible_for_reconciliation() -> None:
    """Second-granularity timestamps must not strand a later same-second review."""
    text = SCHEDULER.read_text(encoding="utf-8")
    assert "fromdateiso8601) >= ($started | fromdateiso8601" in text
    proc = subprocess.run(
        [
            "jq",
            "-nr",
            "--arg",
            "review",
            "2026-09-02T12:00:00Z",
            "--arg",
            "started",
            "2026-09-02T12:00:00Z",
            "try (($review | fromdateiso8601) >= ($started | fromdateiso8601)) catch false",
        ],
        text=True,
        capture_output=True,
        check=True,
    )
    assert proc.stdout.strip() == "true"
