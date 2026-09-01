"""Contract tests for Inkspan's bounded hourly review-repair caller."""

from pathlib import Path


CALLER = Path(".github/workflows/inkspan-hourly-review-repair.yml")
DOCTORING = Path("docs/doctoring/inkspan-hourly-review-caller.md")
QUALITY_WORKFLOW = Path(".github/workflows/hourly-nvidia-nim-review-repair.yml")


def _read(path: Path) -> str:
    """Return one repository contract file as UTF-8 text."""
    return path.read_text(encoding="utf-8")


def test_inkspan_caller_is_hourly_bounded_and_non_cancelling() -> None:
    """Inkspan receives one bounded repair opportunity without overlap cancellation."""
    caller = _read(CALLER)

    assert 'cron: "56 * * * *"' in caller
    assert "group: inkspan-hourly-review-repair" in caller
    assert "cancel-in-progress: false" in caller
    assert "uses: ./.github/workflows/pr-review-fix-scheduler.yml" in caller
    assert "target_repository: ContextualWisdomLab/inkspan" in caller
    assert "base_branch: main" in caller
    assert 'max_prs: "50"' in caller
    assert 'max_dispatches: "1"' in caller
    assert 'retry_hours: "2"' in caller


def test_inkspan_caller_preserves_credentials_and_oidc_scope() -> None:
    """The caller grants only reusable-worker read/OIDC permissions."""
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


def test_inkspan_doctoring_records_governance_and_research_bounds() -> None:
    """Operators retain RCA, credential, approval, and citation contracts."""
    doctoring = _read(DOCTORING)

    for phrase in (
        "root-cause analysis",
        "remediation feasibility",
        "two-hour same-head retry floor",
        "independent non-author approval",
        "NVIDIA_NIM_API_KEY",
        "COPILOT_GITHUB_TOKEN",
        "ContextualWisdomLab/inkspan#299",
        "ContextualWisdomLab/inkspan#362",
        "APA 7th references",
    ):
        assert phrase in doctoring


def test_focused_quality_workflow_tracks_inkspan_caller_contracts() -> None:
    """Caller and doctoring edits rerun exact-head scheduler verification."""
    quality = _read(QUALITY_WORKFLOW)

    assert quality.count(".github/workflows/inkspan-hourly-review-repair.yml") == 2
    assert quality.count("docs/doctoring/inkspan-hourly-review-caller.md") == 2
    assert quality.count("tests/test_inkspan_hourly_review_caller.py") == 3
