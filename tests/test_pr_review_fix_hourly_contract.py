"""Static contracts for the central hourly PR review-fix scheduler."""

from __future__ import annotations

from pathlib import Path


_REUSABLE_WORKFLOW = Path(".github/workflows/pr-review-fix-scheduler.yml")
_CLEARFOLIO_CALLER = Path(".github/workflows/clearfolio-hourly-review-repair.yml")
_CONTRACT_WORKFLOW = Path(".github/workflows/hourly-nvidia-nim-review-repair.yml")


def _read(path: Path) -> str:
    """Return one canonical workflow as UTF-8 text."""
    return path.read_text(encoding="utf-8")


def test_clearfolio_caller_runs_once_each_hour() -> None:
    """Clearfolio receives the requested hourly bounded repair heartbeat."""
    text = _read(_CLEARFOLIO_CALLER)

    assert 'cron: "23 * * * *"' in text
    assert "uses: ./.github/workflows/pr-review-fix-scheduler.yml" in text
    assert "target_repository: ContextualWisdomLab/clearfolio" in text
    assert "base_branch: main" in text
    assert 'max_dispatches: "1"' in text
    assert 'retry_hours: "1"' in text
    assert "COPILOT_GITHUB_TOKEN" not in text
    assert "NVIDIA_NIM_API_KEY" not in text


def test_clearfolio_caller_keeps_github_token_read_only() -> None:
    """The hourly caller delegates with explicit secrets and no token elevation."""
    text = _read(_CLEARFOLIO_CALLER)
    workflow_scope, jobs_scope = text.split("\njobs:\n", maxsplit=1)

    assert "\npermissions:\n  contents: read\n" in workflow_scope
    for permission in (
        "actions: write",
        "issues: write",
        "contents: write",
        "pull-requests: write",
        "statuses: write",
    ):
        assert permission not in text
    assert "\n    permissions:\n" not in jobs_scope


def test_reusable_scheduler_has_no_product_specific_timer() -> None:
    """The shared scheduler stays modular while the caller owns product cadence."""
    text = _read(_REUSABLE_WORKFLOW)
    target_expression = (
        "github.event.client_payload.target_repository || "
        "inputs.target_repository || "
        "vars.PR_REVIEW_FIX_TARGET_REPOSITORY || "
        "github.repository"
    )

    assert "\n  schedule:\n" not in text
    assert text.count(target_expression) == 2
    assert "ContextualWisdomLab/clearfolio" not in text


def test_reusable_scheduler_declares_only_required_caller_secrets() -> None:
    """The caller forwards only established secrets; OIDC supplies the app fallback."""
    reusable = _read(_REUSABLE_WORKFLOW)
    caller = _read(_CLEARFOLIO_CALLER)

    assert "PR_REVIEW_MERGE_TOKEN:" in reusable
    assert "OPENCODE_APPROVE_TOKEN:" in reusable
    assert "PR_REVIEW_MERGE_TOKEN: ${{ secrets.PR_REVIEW_MERGE_TOKEN }}" in caller
    assert "OPENCODE_APPROVE_TOKEN: ${{ secrets.OPENCODE_APPROVE_TOKEN }}" in caller
    assert "secrets: inherit" not in caller
    assert "Exchange OpenCode app token for scheduler mutations" in reusable
    assert "OIDC_AUDIENCE: opencode-github-action" in reusable
    assert (
        "GH_TOKEN: ${{ secrets.PR_REVIEW_MERGE_TOKEN || "
        "secrets.OPENCODE_APPROVE_TOKEN || steps.scheduler_app_token.outputs.token || "
        "github.token }}"
        in reusable
    )
    assert (
        "MUTATION_CREDENTIAL_AVAILABLE: ${{ secrets.PR_REVIEW_MERGE_TOKEN != '' || "
        "secrets.OPENCODE_APPROVE_TOKEN != '' || "
        "steps.scheduler_app_token.outputs.available == 'true' }}"
        in reusable
    )
    assert 'if [ "$MUTATION_CREDENTIAL_AVAILABLE" != "true" ]; then' in reusable
    assert "github.token remains read-only and is never accepted as the mutation authority" in reusable


def test_reusable_scheduler_keeps_workflow_token_read_only() -> None:
    """Repository dispatch never depends on write-capable workflow-token permissions."""
    text = _read(_REUSABLE_WORKFLOW)
    workflow_scope, jobs_scope = text.split("\njobs:\n", maxsplit=1)

    assert "\npermissions:\n  contents: read\n" in workflow_scope
    assert "\n  id-token: write\n" in workflow_scope
    assert "\n    permissions:\n" not in jobs_scope
    for permission in (
        "actions: write",
        "issues: write",
        "contents: write",
        "pull-requests: write",
        "statuses: write",
    ):
        assert permission not in text


def test_review_fix_scheduler_retries_same_head_after_one_hour() -> None:
    """A blocked head can be retried on the next hourly cycle, not a day later."""
    text = _read(_REUSABLE_WORKFLOW)

    retry_block = text.split("retry_hours:", maxsplit=1)[1].split(
        "autofix_workflow:", maxsplit=1
    )[0]
    assert 'default: "1"' in retry_block
    assert "inputs.retry_hours || '1'" in text
    assert "inputs.retry_hours || '24'" not in text


def test_review_fix_scheduler_remains_bounded_and_single_flight() -> None:
    """Higher cadence never expands mutation volume or parallel execution."""
    reusable = _read(_REUSABLE_WORKFLOW)
    caller = _read(_CLEARFOLIO_CALLER)

    dispatch_block = reusable.split("max_dispatches:", maxsplit=1)[1].split(
        "target_repository:", maxsplit=1
    )[0]
    assert 'default: "1"' in dispatch_block
    assert "cancel-in-progress: true" in reusable
    assert "MAX_DISPATCHES" in reusable
    assert "cancel-in-progress: true" in caller


def test_contract_workflow_tracks_the_product_caller() -> None:
    """Changes to the active Clearfolio caller always rerun the focused gate."""
    text = _read(_CONTRACT_WORKFLOW)

    assert text.count(".github/workflows/clearfolio-hourly-review-repair.yml") == 2
