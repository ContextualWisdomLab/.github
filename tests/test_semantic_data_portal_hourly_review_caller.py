"""Contract tests for the semantic-data-portal bounded hourly review-repair caller."""

import re
from pathlib import Path


CALLER = Path(".github/workflows/semantic-data-portal-hourly-review-repair.yml")
DOCTORING = Path("docs/doctoring/semantic-data-portal-hourly-review-caller.md")


def _read(path: Path) -> str:
    """Return one repository contract file as UTF-8 text."""
    return path.read_text(encoding="utf-8")


def _permission_map(caller: str, header: str) -> dict[str, str]:
    """Parse one exact YAML permission block without widening test dependencies."""
    lines = caller.splitlines()
    header_index = lines.index(header)
    entry_indent = len(header) - len(header.lstrip()) + 2
    permissions: dict[str, str] = {}
    for line in lines[header_index + 1 :]:
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        if indent < entry_indent:
            break
        if indent != entry_indent:
            continue
        key, separator, value = line.strip().partition(":")
        assert separator, f"malformed permission entry: {line!r}"
        permissions[key] = value.strip()
    return permissions


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

    assert _permission_map(workflow_scope, "permissions:") == {"contents": "read"}
    assert _permission_map(jobs_scope, "    permissions:") == {
        "contents": "read",
        "id-token": "write",
    }
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
    caller = _read(CALLER)
    assert '- cron: "31 * * * *"' in caller
    other_minutes = {
        minute
        for path in Path(".github/workflows").glob("*hourly-review-repair.yml")
        if path != CALLER
        for minute in re.findall(r'cron:\s*["\'](\d+) \* \* \* \*["\']', _read(path))
    }
    assert "31" not in other_minutes


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
