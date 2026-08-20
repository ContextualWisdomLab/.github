"""Contract tests for Contextual Orchestrator's hourly review caller."""

from pathlib import Path


CALLER = Path(".github/workflows/contextual-orchestrator-hourly-review-repair.yml")
DOCTORING = Path("docs/doctoring/contextual-orchestrator-hourly-review-caller.md")
QUALITY_WORKFLOW = Path(".github/workflows/hourly-nvidia-nim-review-repair.yml")


def _read(path: Path) -> str:
    """Return one required scheduler contract file as UTF-8 text."""
    assert path.is_file(), f"missing required contract file: {path}"
    return path.read_text(encoding="utf-8")


def test_contextual_orchestrator_caller_is_hourly_bounded_and_non_cancelling() -> None:
    """Contextual Orchestrator receives one bounded repair opportunity per hour."""
    caller = _read(CALLER)

    assert 'cron: "17 * * * *"' in caller
    assert "group: contextual-orchestrator-hourly-review-repair" in caller
    assert "cancel-in-progress: false" in caller
    assert "uses: ./.github/workflows/pr-review-fix-scheduler.yml" in caller
    assert "target_repository: ContextualWisdomLab/contextual-orchestrator" in caller
    assert "base_branch: main" in caller
    assert 'max_prs: "50"' in caller
    assert 'max_dispatches: "1"' in caller
    assert 'retry_hours: "1"' in caller


def test_contextual_orchestrator_caller_keeps_credentials_explicit_and_read_only() -> None:
    """The caller forwards only established scheduler credentials."""
    caller = _read(CALLER)
    workflow_scope, jobs_scope = caller.split("\njobs:\n", maxsplit=1)

    assert "\npermissions:\n  contents: read\n" in workflow_scope
    assert "\n    permissions:\n      contents: read\n      id-token: write\n" in jobs_scope
    assert "PR_REVIEW_MERGE_TOKEN: ${{ secrets.PR_REVIEW_MERGE_TOKEN }}" in caller
    assert "OPENCODE_APPROVE_TOKEN: ${{ secrets.OPENCODE_APPROVE_TOKEN }}" in caller
    assert "secrets: inherit" not in caller
    assert "COPILOT_GITHUB_TOKEN" not in caller
    for forbidden in (
        "BYTEZ_API_KEY",
        "NVIDIA_NIM_API_KEY",
        "NVIDIA_NIM_API_KEY_SUB",
        "OPENROUTER_API_KEY",
        "OPENAI_API_KEY",
        "actions: write",
        "contents: write",
        "issues: write",
        "pull-requests: write",
        "statuses: write",
    ):
        assert forbidden not in caller


def test_contextual_orchestrator_doctoring_records_next_operator_action() -> None:
    """The doctoring record tells operators how to handle gates and credentials."""
    doctoring = _read(DOCTORING)

    for phrase in (
        "ContextualWisdomLab/contextual-orchestrator",
        "root-cause analysis",
        "exact PR head",
        "independent reviewer",
        "PR_REVIEW_MERGE_TOKEN",
        "OPENCODE_APPROVE_TOKEN",
        "COPILOT_GITHUB_TOKEN",
        "APA 7th edition",
    ):
        assert phrase in doctoring


def test_focused_quality_workflow_tracks_contextual_orchestrator_contracts() -> None:
    """Caller and doctoring edits rerun the exact-head focused scheduler gate."""
    quality = _read(QUALITY_WORKFLOW)
    caller = ".github/workflows/contextual-orchestrator-hourly-review-repair.yml"
    doctoring = "docs/doctoring/contextual-orchestrator-hourly-review-caller.md"
    contract = "tests/test_contextual_orchestrator_hourly_review_caller.py"

    assert quality.count(caller) == 2
    assert quality.count(doctoring) == 2
    assert quality.count(contract) == 3
