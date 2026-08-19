"""Contract tests for LineageWeave's bounded hourly review-repair caller."""

from pathlib import Path


CALLER = Path(".github/workflows/lineageweave-hourly-review-repair.yml")
QUALITY_WORKFLOW = Path(
    ".github/workflows/lineageweave-hourly-review-repair-quality.yml"
)
DOCTORING = Path("docs/doctoring/lineageweave-hourly-review-caller.md")
INCIDENT = Path("docs/doctoring/lineageweave-buyer-surface-opencode-incident.md")
SCHEDULER = Path(".github/workflows/pr-review-fix-scheduler.yml")


def _read(path: Path) -> str:
    """Return one repository contract file as UTF-8 text."""

    return path.read_text(encoding="utf-8")


def test_lineageweave_caller_is_manual_hourly_bounded_and_non_cancelling() -> None:
    """LineageWeave receives one bounded repair without cancelling live RCA work."""

    caller = _read(CALLER)

    assert "workflow_dispatch:" in caller
    assert 'cron: "4 * * * *"' in caller
    assert "group: lineageweave-hourly-review-repair" in caller
    assert "cancel-in-progress: false" in caller
    assert "uses: ./.github/workflows/pr-review-fix-scheduler.yml" in caller
    assert "target_repository: ContextualWisdomLab/LineageWeave" in caller
    assert "base_branch: main" in caller
    assert 'max_prs: "50"' in caller
    assert 'max_dispatches: "1"' in caller
    assert 'retry_hours: "2"' in caller


def test_lineageweave_caller_preserves_oidc_and_explicit_secret_scope() -> None:
    """The caller maps established credentials without model or mutation scope."""

    caller = _read(CALLER)
    workflow_scope, jobs_scope = caller.split("\njobs:\n", maxsplit=1)

    assert "\npermissions:\n  contents: read\n" in workflow_scope
    assert (
        "\n    permissions:\n      contents: read\n      id-token: write\n"
        in jobs_scope
    )
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


def test_lineageweave_target_is_not_hard_coded_in_shared_scheduler() -> None:
    """Product identity remains in the thin caller rather than the engine."""

    assert "ContextualWisdomLab/LineageWeave" not in _read(SCHEDULER)


def test_lineageweave_doctoring_preserves_operational_boundaries() -> None:
    """The original doctoring retains target, credential, and approval rules."""

    doctoring = _read(DOCTORING)

    for phrase in (
        "ContextualWisdomLab/LineageWeave",
        "OPENCODE_REPOSITORY_DISPATCH_TARGETS",
        "independent non-author approval",
        "NVIDIA_NIM_API_KEY",
        "COPILOT_GITHUB_TOKEN",
        "id-token: write",
        "two-hour same-head retry floor",
        "root-cause analysis",
        "remediation feasibility",
        "protected-main operational acceptance",
        "APA 7th references",
    ):
        assert phrase in doctoring


def test_incident_doctoring_tracks_current_buyer_surface_stack() -> None:
    """The incident record names the live stack and end-to-end acceptance path."""

    incident = _read(INCIDENT)

    for phrase in (
        "#258 → #260 → #261 → #262 → #263 → #264",
        "@opencode-agent",
        "exact invocation ledger",
        "neither a visible receipt",
        "formal OpenCode review",
        "no duplicate dispatch",
        "dependency order",
        "APA 7th references",
    ):
        assert phrase in incident


def test_focused_quality_workflow_tracks_every_owned_contract() -> None:
    """Caller, quality, test, and both doctoring records rerun the focused gate."""

    quality = _read(QUALITY_WORKFLOW)
    owned_paths = (
        ".github/workflows/lineageweave-hourly-review-repair.yml",
        ".github/workflows/lineageweave-hourly-review-repair-quality.yml",
        "tests/test_lineageweave_hourly_review_caller.py",
        "docs/doctoring/lineageweave-hourly-review-caller.md",
        "docs/doctoring/lineageweave-buyer-surface-opencode-incident.md",
    )

    assert "\npermissions:\n  contents: read\n" in quality
    assert "cancel-in-progress: true" in quality
    assert "persist-credentials: false" in quality
    assert "--require-hashes" in quality
    assert "tests/test_lineageweave_hourly_review_caller.py" in quality
    assert "python -m compileall -q \\" in quality
    assert "git diff --check" in quality
    for path in owned_paths:
        assert quality.count(f"      - {path}") == 2
    for forbidden in (
        "actions: write",
        "contents: write",
        "issues: write",
        "pull-requests: write",
        "secrets: inherit",
        "NVIDIA_NIM_API_KEY",
        "COPILOT_GITHUB_TOKEN",
    ):
        assert forbidden not in quality
