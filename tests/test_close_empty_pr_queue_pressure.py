"""Regression contracts for close-event runner admission pressure."""

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
    assert "github.event.pull_request.head.sha" not in concurrency
    assert "cancel-in-progress:" in concurrency
    assert "cancel-closed-pr-runs:" not in workflow
    assert "github.event.action != 'closed'" in workflow
    assert evidence_job in workflow
