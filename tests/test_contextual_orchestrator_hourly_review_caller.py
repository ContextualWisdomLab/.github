"""Contract tests for the contextual-orchestrator hourly repair caller."""

from pathlib import Path


CALLER = Path(
    ".github/workflows/contextual-orchestrator-hourly-review-repair.yml"
)
DOCTORING = Path(
    "docs/doctoring/contextual-orchestrator-hourly-review-caller.md"
)
QUALITY_WORKFLOW = Path(".github/workflows/hourly-nvidia-nim-review-repair.yml")
CONTRACT = Path("tests/test_contextual_orchestrator_hourly_review_caller.py")


def _read(path: Path) -> str:
    """Return one required contract file as UTF-8 text."""
    assert path.is_file(), f"missing required contract file: {path}"
    return path.read_text(encoding="utf-8")


def test_caller_is_hourly_bounded_and_non_cancelling() -> None:
    """Give the target repository one bounded repair scan per hour."""
    caller = _read(CALLER)

    assert 'cron: "17 * * * *"' in caller
    assert "group: contextual-orchestrator-hourly-review-repair" in caller
    assert "cancel-in-progress: false" in caller
    assert "uses: ./.github/workflows/pr-review-fix-scheduler.yml" in caller
    assert "target_repository: ContextualWisdomLab/contextual-orchestrator" in caller
    assert "base_branch: main" in caller
    assert 'max_prs: "50"' in caller
    assert 'max_dispatches: "1"' in caller
    assert "resolve_unreviewed_conflicts: true" in caller
    assert 'retry_hours: "2"' in caller


def test_caller_preserves_oidc_and_explicit_scheduler_secret_scope() -> None:
    """Forward only established scheduler credentials to the reusable workflow."""
    caller = _read(CALLER)
    workflow_scope, jobs_scope = caller.split("\njobs:\n", maxsplit=1)

    assert "\npermissions:\n  contents: read\n" in workflow_scope
    assert "\n    permissions:\n      contents: read\n      id-token: write\n" in jobs_scope
    assert "PR_REVIEW_MERGE_TOKEN: ${{ secrets.PR_REVIEW_MERGE_TOKEN }}" in caller
    assert "OPENCODE_APPROVE_TOKEN: ${{ secrets.OPENCODE_APPROVE_TOKEN }}" in caller
    assert "secrets: inherit" not in caller
    assert "NVIDIA_NIM_API_KEY" not in caller
    assert "COPILOT_GITHUB_TOKEN" not in caller
    for forbidden in (
        "actions: write",
        "contents: write",
        "issues: write",
        "pull-requests: write",
        "statuses: write",
    ):
        assert forbidden not in caller


def test_doctoring_records_gateway_dependency_and_customer_next_action() -> None:
    """Tell operators which gateway PR must land before this caller is enabled."""
    doctoring = _read(DOCTORING)

    for phrase in (
        "ContextualWisdomLab/contextual-orchestrator",
        "#1168",
        "contextual-orchestrator gateway",
        "exact-head",
        "independent review",
        "OPENCODE_REPOSITORY_DISPATCH_TARGETS",
        "PR_REVIEW_MERGE_TOKEN",
        "OPENCODE_APPROVE_TOKEN",
        "NVIDIA_NIM_API_KEY",
        "COPILOT_GITHUB_TOKEN",
        "APA 7th references",
    ):
        assert phrase in doctoring


def test_quality_workflow_tracks_caller_test_and_doctoring() -> None:
    """Run the focused quality gate when any caller contract changes."""
    quality = _read(QUALITY_WORKFLOW)
    for path in (CALLER, DOCTORING, CONTRACT):
        assert quality.count(str(path)) >= 2
    assert str(CONTRACT) in quality[quality.index("python -m compileall"):]
