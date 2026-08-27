"""Contract tests for the learning-contracts bounded hourly review-repair caller."""

from pathlib import Path


CALLER = Path(
    ".github/workflows/learning-interoperability-contracts-hourly-review-repair.yml"
)
DOCTORING = Path(
    "docs/doctoring/learning-interoperability-contracts-hourly-review-caller.md"
)
QUALITY_WORKFLOW = Path(
    ".github/workflows/learning-interoperability-contracts-hourly-review-repair-quality.yml"
)


def _read(path: Path) -> str:
    """Return one required repository contract file as UTF-8 text."""
    assert path.is_file(), f"missing required contract file: {path}"
    return path.read_text(encoding="utf-8")


def test_learning_contracts_caller_scans_every_base_hourly_and_is_bounded() -> None:
    """Stacked contract PRs receive one bounded non-cancelling hourly heartbeat."""
    caller = _read(CALLER)

    assert 'cron: "18 * * * *"' in caller
    assert "group: learning-interoperability-contracts-hourly-review-repair" in caller
    assert "cancel-in-progress: false" in caller
    assert "uses: ./.github/workflows/pr-review-fix-scheduler.yml" in caller
    assert (
        "target_repository: ContextualWisdomLab/learning-interoperability-contracts"
        in caller
    )
    assert 'base_branch: "*"' in caller
    assert 'max_prs: "50"' in caller
    assert 'max_dispatches: "1"' in caller
    assert 'retry_hours: "2"' in caller


def test_learning_contracts_caller_preserves_oidc_and_credential_scope() -> None:
    """The caller grants only read and OIDC while mapping scheduler credentials."""
    caller = _read(CALLER)
    workflow_scope, jobs_scope = caller.split("\njobs:\n", maxsplit=1)
    pr_review_secret = "$" + "{{ secrets.PR_REVIEW_MERGE_TOKEN }}"
    opencode_secret = "$" + "{{ secrets.OPENCODE_APPROVE_TOKEN }}"

    assert "\npermissions:\n  contents: read\n" in workflow_scope
    assert (
        "\n    permissions:\n"
        "      contents: read\n"
        "      id-token: write\n"
    ) in jobs_scope
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


def test_learning_contracts_doctoring_preserves_standards_and_rights_bounds() -> None:
    """Operators retain standards, rights, credential, and approval contracts."""
    doctoring = _read(DOCTORING)

    for phrase in (
        "rights-safe contract authority",
        "all PR bases",
        "two-hour same-head retry floor",
        "official CEFR descriptor prose",
        "xAPI 2.0",
        "independent non-author approval",
        "id-token: write",
        "OPENCODE_REPOSITORY_DISPATCH_TARGETS",
        "NVIDIA_NIM_API_KEY",
        "COPILOT_GITHUB_TOKEN",
        "ContextualWisdomLab/learning-interoperability-contracts",
        "APA 7th references",
    ):
        assert phrase in doctoring


def test_focused_quality_workflow_tracks_learning_contracts_contracts() -> None:
    """Caller and doctoring edits always rerun exact-head verification."""
    quality = _read(QUALITY_WORKFLOW)

    assert (
        quality.count(
            ".github/workflows/learning-interoperability-contracts-hourly-review-repair.yml"
        )
        == 2
    )
    assert (
        quality.count(
            "docs/doctoring/learning-interoperability-contracts-hourly-review-caller.md"
        )
        == 2
    )
    assert (
        quality.count(
            "tests/test_learning_interoperability_contracts_hourly_review_caller.py"
        )
        == 3
    )
    assert "ref: ${{ github.event.pull_request.head.sha || github.sha }}" in quality
    assert "persist-credentials: false" in quality
    assert "--require-hashes" in quality
    assert "git diff --check" in quality
