"""Supply-chain contract for the reusable PR-review autofix scheduler."""

from __future__ import annotations

from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[1]
_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "pr-review-fix-scheduler.yml"


def _workflow_text() -> str:
    """Read the reusable scheduler workflow as UTF-8 text."""
    return _WORKFLOW.read_text(encoding="utf-8")


def test_reusable_scheduler_checks_out_the_called_workflow_sha() -> None:
    """Privileged scheduler code comes from the immutable called-workflow revision."""
    workflow = _workflow_text()
    assert "repository: ${{ job.workflow_repository }}" in workflow
    assert "ref: ${{ job.workflow_sha }}" in workflow
    assert "persist-credentials: false" in workflow


def test_reusable_scheduler_source_is_not_caller_input_controlled() -> None:
    """No caller-supplied ref or ordinary caller GitHub SHA selects trusted code."""
    workflow = _workflow_text()
    assert "inputs.canonical_ref" not in workflow
    assert "github.event.client_payload.canonical_ref" not in workflow
    assert "ref: ${{ env.CANONICAL_REF }}" not in workflow
    assert "ref: ${{ github.sha }}" not in workflow


def test_deprecated_canonical_ref_input_is_accepted_but_never_consumed() -> None:
    """Existing callers can upgrade pins without controlling privileged source."""
    workflow = _workflow_text()
    declaration = workflow.split("canonical_ref:", 1)[1].split(
        "repository_dispatch:", 1
    )[0]

    assert "Deprecated compatibility input" in declaration
    assert "ignored" in declaration
    assert 'default: ""' in declaration
    assert workflow.count("canonical_ref") == 1


def test_reusable_scheduler_retains_least_privilege_and_bounded_dispatch() -> None:
    """Source pinning does not broaden token scope or queue fan-out."""
    workflow = _workflow_text()
    assert "contents: write" not in workflow
    assert "pull-requests: write" not in workflow
    assert "MAX_DISPATCHES:" in workflow
    assert "RETRY_HOURS:" in workflow
    assert "cancel-in-progress: true" in workflow
