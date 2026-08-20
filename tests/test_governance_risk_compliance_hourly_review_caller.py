"""Contract tests for the GRC product's bounded hourly review-repair caller."""

from pathlib import Path


CALLER = Path(".github/workflows/governance-risk-compliance-hourly-review-repair.yml")
DOCTORING = Path("docs/doctoring/governance-risk-compliance-hourly-review-caller.md")
QUALITY_WORKFLOW = Path(".github/workflows/hourly-nvidia-nim-review-repair.yml")


def _read(path: Path) -> str:
    """Return one repository contract file as UTF-8 text."""
    return path.read_text(encoding="utf-8")


def test_grc_caller_is_hourly_bounded_and_non_cancelling() -> None:
    """GRC receives one realistic exact-head repair opportunity per heartbeat."""
    caller = _read(CALLER)

    assert 'cron: "43 * * * *"' in caller
    assert "group: governance-risk-compliance-hourly-review-repair" in caller
    assert "cancel-in-progress: false" in caller
    assert "uses: ./.github/workflows/pr-review-fix-scheduler.yml" in caller
    assert "target_repository: ContextualWisdomLab/governance-risk-compliance" in caller
    assert "base_branch: develop" in caller
    assert 'max_prs: "50"' in caller
    assert 'max_dispatches: "1"' in caller
    assert 'retry_hours: "2"' in caller


def test_grc_caller_preserves_credentials_and_read_only_scope() -> None:
    """The caller maps scheduler credentials without exposing provider secrets."""
    caller = _read(CALLER)
    workflow_scope, jobs_scope = caller.split("\njobs:\n", maxsplit=1)
    pr_review_secret = "$" + "{{ secrets.PR_REVIEW_MERGE_TOKEN }}"
    opencode_secret = "$" + "{{ secrets.OPENCODE_APPROVE_TOKEN }}"

    assert "\npermissions:\n  contents: read\n" in workflow_scope
    assert "\n    permissions:\n      contents: read\n      id-token: write\n" in jobs_scope
    assert f"PR_REVIEW_MERGE_TOKEN: {pr_review_secret}" in caller
    assert f"OPENCODE_APPROVE_TOKEN: {opencode_secret}" in caller
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


def test_grc_doctoring_records_product_and_governance_bounds() -> None:
    """Operators retain RCA, ownership, credential, and approval contracts."""
    doctoring = _read(DOCTORING)

    for phrase in (
        "root-cause analysis",
        "remediation feasibility",
        "two-hour same-head retry floor",
        "policy, control, risk, evidence, and compliance-audit truth",
        "Keyverse",
        "independent non-author approval",
        "NVIDIA_NIM_API_KEY",
        "COPILOT_GITHUB_TOKEN",
        "ContextualWisdomLab/governance-risk-compliance",
        "APA 7th references",
    ):
        assert phrase in doctoring


def test_focused_quality_workflow_tracks_grc_contracts() -> None:
    """Caller, doctoring, and contract edits always rerun exact-head verification."""
    quality = _read(QUALITY_WORKFLOW)

    assert quality.count(
        ".github/workflows/governance-risk-compliance-hourly-review-repair.yml"
    ) == 2
    assert quality.count(
        "docs/doctoring/governance-risk-compliance-hourly-review-caller.md"
    ) == 2
    assert quality.count("tests/test_governance_risk_compliance_hourly_review_caller.py") == 3
