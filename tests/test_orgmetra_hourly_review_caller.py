"""Contract tests for Orgmetra's bounded hourly review-repair caller."""

from pathlib import Path


CALLER = Path(".github/workflows/orgmetra-hourly-review-repair.yml")
DOCTORING = Path("docs/doctoring/orgmetra-hourly-review-caller.md")
QUALITY_WORKFLOW = Path(".github/workflows/hourly-nvidia-nim-review-repair.yml")


def _read(path: Path) -> str:
    """Return one repository contract file as UTF-8 text."""
    return path.read_text(encoding="utf-8")


def _path_block(quality: str, trigger: str) -> set[str]:
    """Return the path entries under one focused workflow trigger."""
    marker = f"  {trigger}:\n    paths:\n"
    start = quality.index(marker) + len(marker)
    entries: set[str] = set()
    for line in quality[start:].splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if not stripped.startswith("-"):
            break
        entries.add(stripped[1:].strip())
    return entries


def test_orgmetra_caller_is_hourly_bounded_and_non_cancelling() -> None:
    """Orgmetra receives one protected-develop repair opportunity per heartbeat."""
    caller = _read(CALLER)

    assert 'cron: "58 * * * *"' in caller
    assert "group: orgmetra-hourly-review-repair" in caller
    assert "cancel-in-progress: false" in caller
    assert "uses: ./.github/workflows/pr-review-fix-scheduler.yml" in caller
    assert "target_repository: ContextualWisdomLab/Orgmetra" in caller
    assert "base_branch: develop" in caller
    assert 'max_prs: "50"' in caller
    assert 'max_dispatches: "1"' in caller
    assert 'retry_hours: "2"' in caller


def test_orgmetra_caller_keeps_scheduler_credentials_explicit() -> None:
    """The queue scanner receives only its established scheduler credentials."""
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


def test_orgmetra_doctoring_records_runtime_and_governance_bounds() -> None:
    """Operators retain the product, HCM, provider, and approval boundaries."""
    doctoring = _read(DOCTORING)

    for phrase in (
        "ContextualWisdomLab/Orgmetra",
        "protected develop",
        "root-cause analysis",
        "remediation feasibility",
        "two-hour same-head retry floor",
        "contextual-orchestrator",
        "automatic model discovery",
        "NVIDIA_NIM_API_KEY",
        "COPILOT_GITHUB_TOKEN",
        "independent non-author approval",
        "APA 7th references",
    ):
        assert phrase in doctoring
    assert "protected\nprotected" not in doctoring


def test_focused_quality_workflow_tracks_orgmetra_contracts() -> None:
    """Caller, test, and doctoring edits stay inside the focused quality gate."""
    quality = _read(QUALITY_WORKFLOW)
    caller = ".github/workflows/orgmetra-hourly-review-repair.yml"
    doctoring = "docs/doctoring/orgmetra-hourly-review-caller.md"
    contract = "tests/test_orgmetra_hourly_review_caller.py"

    for trigger in ("pull_request", "push"):
        paths = _path_block(quality, trigger)
        assert caller in paths
        assert doctoring in paths
        assert contract in paths

    compileall_start = quality.index("python -m compileall -q \\")
    compileall_end = quality.index("git diff --check", compileall_start)
    compileall = quality[compileall_start:compileall_end]
    assert contract in compileall
