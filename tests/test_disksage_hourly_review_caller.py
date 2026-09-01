"""Contract tests for DiskSage's bounded hourly review-repair caller."""

from pathlib import Path


CALLER = Path(".github/workflows/disksage-hourly-review-repair.yml")
DOCTORING = Path("docs/doctoring/disksage-hourly-review-caller.md")
QUALITY_WORKFLOW = Path(".github/workflows/hourly-nvidia-nim-review-repair.yml")


def _read(path: Path) -> str:
    """Return one repository contract file as UTF-8 text."""
    return path.read_text(encoding="utf-8")


def test_disksage_caller_is_hourly_bounded_and_non_cancelling() -> None:
    """DiskSage receives one realistic repair opportunity without overlap cancellation."""
    caller = _read(CALLER)

    assert 'cron: "37 * * * *"' in caller
    assert "group: disksage-hourly-review-repair" in caller
    assert "cancel-in-progress: false" in caller
    assert "uses: ./.github/workflows/pr-review-fix-scheduler.yml" in caller
    assert "target_repository: ContextualWisdomLab/disksage" in caller
    assert "base_branch: main" in caller
    assert 'max_prs: "50"' in caller
    assert 'max_dispatches: "1"' in caller
    assert 'retry_hours: "2"' in caller


def test_disksage_caller_preserves_credentials_and_read_only_token_scope() -> None:
    """The queue scanner maps established credentials without exposing model secrets."""
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


def test_disksage_caller_doctoring_records_rca_feasibility_and_latency() -> None:
    """Operators retain the exact rationale for the bounded two-hour retry policy."""
    doctoring = _read(DOCTORING)

    for phrase in (
        "root-cause analysis",
        "remediation feasibility",
        "two-hour same-head retry floor",
        "independent non-author approval",
        "NVIDIA_NIM_API_KEY",
        "COPILOT_GITHUB_TOKEN",
        "ContextualWisdomLab/disksage",
        "APA 7th references",
    ):
        assert phrase in doctoring


def test_focused_quality_workflow_tracks_disksage_caller_contracts() -> None:
    """Every caller or doctoring edit reruns exact-head scheduler verification."""
    quality = _read(QUALITY_WORKFLOW)

    assert quality.count(".github/workflows/disksage-hourly-review-repair.yml") == 2
    assert quality.count("docs/doctoring/disksage-hourly-review-caller.md") == 2
    assert quality.count("tests/test_disksage_hourly_review_caller.py") == 3
