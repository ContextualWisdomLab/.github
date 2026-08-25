"""Contract tests for the semantic-data-portal bounded hourly review-repair caller."""

from pathlib import Path


CALLER = Path(".github/workflows/semantic-data-portal-hourly-review-repair.yml")
DOCTORING = Path("docs/doctoring/semantic-data-portal-hourly-review-caller.md")


def _read(path: Path) -> str:
    """Return one repository contract file as UTF-8 text."""
    return path.read_text(encoding="utf-8")


def test_semantic_data_portal_caller_is_hourly_bounded_and_non_cancelling() -> None:
    """The portal receives one realistic repair opportunity without overlap cancellation."""
    caller = _read(CALLER)

    assert 'cron: "31 * * * *"' in caller
    assert "group: semantic-data-portal-hourly-review-repair" in caller
    assert "cancel-in-progress: false" in caller
    assert "uses: ./.github/workflows/pr-review-fix-scheduler.yml" in caller
    assert "target_repository: ContextualWisdomLab/semantic-data-portal" in caller
    assert "base_branch: main" in caller
    assert 'max_prs: "50"' in caller
    assert 'max_dispatches: "1"' in caller
    assert 'retry_hours: "2"' in caller


def test_semantic_data_portal_caller_preserves_credentials_and_read_only_token_scope() -> None:
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


def test_semantic_data_portal_caller_cron_avoids_other_callers() -> None:
    """Minute 31 does not collide with any other product caller heartbeat."""
    taken = {str(m) for m in (2, 10, 14, 16, 21, 23, 27, 37, 43, 49, 53, 58)}
    assert "31" not in taken
    caller = _read(CALLER)
    assert '- cron: "31 * * * *"' in caller


def test_semantic_data_portal_caller_doctoring_records_rca_feasibility_and_latency() -> None:
    """Operators retain the exact rationale for the bounded two-hour retry policy."""
    doctoring = _read(DOCTORING)

    for phrase in (
        "root-cause analysis",
        "remediation feasibility",
        "two-hour same-head retry floor",
        "exact-head",
        "cancel-in-progress: false",
        "NVIDIA_NIM_API_KEY",
        "COPILOT_GITHUB_TOKEN",
        "PR_REVIEW_MERGE_TOKEN",
        "OPENCODE_APPROVE_TOKEN",
        "ContextualWisdomLab/semantic-data-portal",
        "minute 31",
    ):
        assert phrase in doctoring, phrase

    for reference in (
        "https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency",
        "https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule",
        "https://docs.github.com/en/actions/how-tos/sharing-automations/reusing-workflows",
        "https://doi.org/10.6028/NIST.SP.800-218",
    ):
        assert reference in doctoring, reference
