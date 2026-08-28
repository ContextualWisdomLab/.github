"""Contract tests for LineageWeave's bounded hourly review-repair caller."""

from pathlib import Path


CALLER = Path(".github/workflows/lineageweave-hourly-review-repair.yml")
DOCTORING = Path("docs/doctoring/lineageweave-hourly-review-caller.md")
QUALITY_WORKFLOW = Path(".github/workflows/hourly-nvidia-nim-review-repair.yml")
SCHEDULER = Path(".github/workflows/pr-review-fix-scheduler.yml")


def _read(path: Path) -> str:
    """Return one repository contract file as UTF-8 text."""
    return path.read_text(encoding="utf-8")


def test_lineageweave_caller_is_hourly_bounded_and_stack_aware() -> None:
    """The stacked repository receives one non-cancelling repair opportunity."""
    caller = _read(CALLER)

    for contract in (
        'cron: "4 * * * *"',
        "group: lineageweave-hourly-review-repair",
        "cancel-in-progress: false",
        "uses: ./.github/workflows/pr-review-fix-scheduler.yml",
        "target_repository: ContextualWisdomLab/LineageWeave",
        'base_branch: "*"',
        'max_prs: "50"',
        'max_dispatches: "1"',
        'retry_hours: "2"',
    ):
        assert contract in caller


def test_lineageweave_caller_preserves_the_existing_credential_boundary() -> None:
    """The caller maps only scheduler credentials and exposes no model secret."""
    caller = _read(CALLER)
    workflow_scope, jobs_scope = caller.split("\njobs:\n", maxsplit=1)

    assert "\npermissions:\n  contents: read\n" in workflow_scope
    assert "\n    permissions:\n      contents: read\n      id-token: write\n" in jobs_scope
    assert "PR_REVIEW_MERGE_TOKEN: ${{ secrets.PR_REVIEW_MERGE_TOKEN }}" in caller
    assert "OPENCODE_APPROVE_TOKEN: ${{ secrets.OPENCODE_APPROVE_TOKEN }}" in caller
    assert "secrets: inherit" not in caller
    assert "COPILOT_GITHUB_TOKEN" not in caller
    assert "NVIDIA_NIM_API_KEY" not in caller
    assert "LLM_GATEWAY_API_URL" not in caller
    assert "ContextualWisdomLab/LineageWeave" not in _read(SCHEDULER)


def test_lineageweave_caller_is_covered_by_the_focused_quality_gate() -> None:
    """Caller, evidence, and regression test all trigger the focused gate."""
    quality = _read(QUALITY_WORKFLOW)

    assert quality.count(str(CALLER)) == 2
    assert quality.count(str(DOCTORING)) == 2
    assert quality.count("tests/test_lineageweave_hourly_review_caller.py") == 3


def test_lineageweave_doctoring_keeps_product_and_review_claims_separate() -> None:
    """The evidence record states what this caller can and cannot prove."""
    doctoring = _read(DOCTORING).lower()

    for contract in (
        "stacked pull requests",
        "independent current-head approval",
        "does not create product work",
        "contextual-orchestrator",
        "copilot_github_token",
        "apa 7th references",
    ):
        assert contract in doctoring
