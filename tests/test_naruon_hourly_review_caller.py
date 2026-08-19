"""Contract tests for naruon's bounded hourly review-repair caller."""

from pathlib import Path


CALLER = Path(".github/workflows/naruon-hourly-review-repair.yml")
DOCTORING = Path("docs/doctoring/naruon-hourly-review-caller.md")
QUALITY_WORKFLOW = Path(".github/workflows/hourly-nvidia-nim-review-repair.yml")


def _read(path: Path) -> str:
    """Return one repository contract file as UTF-8 text."""
    return path.read_text(encoding="utf-8")


def test_naruon_caller_is_hourly_bounded_and_non_cancelling() -> None:
    """naruon gets one protected-develop repair heartbeat per hour."""
    caller = _read(CALLER)

    assert 'cron: "11 * * * *"' in caller
    assert "group: naruon-hourly-review-repair" in caller
    assert "cancel-in-progress: false" in caller
    assert "uses: ./.github/workflows/pr-review-fix-scheduler.yml" in caller
    assert "target_repository: ContextualWisdomLab/naruon" in caller
    assert "base_branch: develop" in caller
    assert 'max_prs: "50"' in caller
    assert 'max_dispatches: "1"' in caller
    assert 'retry_hours: "2"' in caller


def test_naruon_caller_keeps_token_and_secret_scope_explicit() -> None:
    """The caller forwards only established scheduler credentials."""
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


def test_naruon_contract_and_doctoring_are_path_filtered() -> None:
    """The central contract gate follows caller and doctoring changes."""
    quality = _read(QUALITY_WORKFLOW)
    for path in (
        ".github/workflows/naruon-hourly-review-repair.yml",
        "docs/doctoring/naruon-hourly-review-caller.md",
    ):
        assert quality.count(path) == 2
    assert quality.count("tests/test_naruon_hourly_review_caller.py") == 3

    doctoring = _read(DOCTORING)
    for phrase in (
        "ContextualWisdomLab/naruon",
        "minute 11",
        "base",
        "two-hour same-head retry floor",
        "NVIDIA_NIM_API_KEY",
        "COPILOT_GITHUB_TOKEN",
        "independent approval",
    ):
        assert phrase in doctoring
