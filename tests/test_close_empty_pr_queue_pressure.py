"""Regression contracts for close-event runner admission pressure."""

import re
from pathlib import Path

import pytest


WORKFLOWS = Path(__file__).parents[1] / ".github/workflows"


@pytest.mark.parametrize(
    ("filename", "evidence_job"),
    (
        ("codeql-pr.yml", "  detect-languages:"),
        ("pr-review-merge-scheduler.yml", "  scan-pr-queue:"),
        ("python-security.yml", "  detect-python:"),
        ("sast-semgrep.yml", "  semgrep:"),
        ("security-scan.yml", "  osv-scan:"),
    ),
)
def test_closed_pull_request_does_not_allocate_a_noop_runner(
    filename: str,
    evidence_job: str,
) -> None:
    """PR-stable concurrency retires close work without a no-op runner."""
    workflow = (WORKFLOWS / filename).read_text(encoding="utf-8")
    concurrency = workflow.split("concurrency:", 1)[1].split("permissions:", 1)[0]

    assert "closed" in workflow
    assert "github.event.pull_request.number" in concurrency
    if filename == "pr-review-merge-scheduler.yml":
        assert "github.event.pull_request.head.sha" in concurrency
        assert "queue: max" in concurrency
        assert "cancel-in-progress:" not in concurrency
        cleanup_job = workflow.split(
            "  cancel-superseded-pr-runs:", 1
        )[1].split("  scan-pr-queue:", 1)[0]
        assert "actions: write" in cleanup_job
        assert "actions/checkout" not in cleanup_job
        assert "github.event.action == 'closed'" in cleanup_job
        assert "TARGET_PR_NUMBER" in cleanup_job
        assert "TARGET_PR_HEAD_SHA" in cleanup_job
    else:
        assert "github.event.pull_request.head.sha" not in concurrency
        assert re.search(r"(?m)^[ \t]+cancel-in-progress:[ \t]+\S", concurrency)
    assert "cancel-closed-pr-runs:" not in workflow
    assert "github.event.action != 'closed'" in workflow
    assert evidence_job in workflow
