"""Contract tests for LineageWeave's bounded hourly review-repair caller."""

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CALLER = REPO_ROOT / ".github/workflows/lineageweave-hourly-review-repair.yml"
QUALITY_WORKFLOW = REPO_ROOT / ".github/workflows/lineageweave-hourly-review-repair-quality.yml"
STACK_DRIVER = REPO_ROOT / "scripts/ci/pr_review_fix_stack_scheduler.py"
MERGE_DRIVER = REPO_ROOT / "scripts/ci/pr_review_merge_scheduler.py"
DOCTORING = REPO_ROOT / "docs/doctoring/lineageweave-hourly-review-caller.md"
INCIDENT = REPO_ROOT / "docs/doctoring/lineageweave-buyer-surface-opencode-incident.md"
ONE_SHOT = REPO_ROOT / ".github/workflows/one-shot-repair-lineageweave-stack.yml"


def _read(path: Path) -> str:
    """Return one repository contract file as UTF-8 text."""

    return path.read_text(encoding="utf-8")


def test_lineageweave_caller_is_hourly_bounded_and_ordered() -> None:
    """The heartbeat covers all six PRs and permits one dependency-safe repair."""

    caller = _read(CALLER)

    assert "workflow_dispatch:" not in caller
    assert 'cron: "4 * * * *"' in caller
    assert "group: lineageweave-hourly-review-repair" in caller
    assert "cancel-in-progress: false" in caller
    assert "TARGET_REPOSITORY: ContextualWisdomLab/LineageWeave" in caller
    assert "ROOT_BASE_BRANCH: main" in caller
    assert 'PULL_REQUEST_NUMBERS: "258,260,261,262,263,264"' in caller
    assert 'MAX_PRS: "6"' in caller
    assert 'MAX_DISPATCHES: "1"' in caller
    assert 'OPEN_PR_SCAN_LIMIT: "1000"' in caller
    assert 'RETRY_HOURS: "2"' in caller
    assert "pr_review_fix_stack_scheduler.py" in caller
    assert "pr_review_merge_scheduler.py" in caller
    assert "--stacked-only" in caller
    assert "--review-dispatch-limit 1" in caller
    assert "--branch-update-limit 0" in caller
    assert "--no-enable-auto-merge" in caller
    assert "--merge-mode disabled" in caller
    assert "--no-update-branches" in caller
    assert "--pull-request-numbers \"$PULL_REQUEST_NUMBERS\"" in caller


def test_lineageweave_caller_is_protected_main_only_and_least_privilege() -> None:
    """Only protected central main can materialize the established mutation path."""

    caller = _read(CALLER)

    assert "contents: read" in caller
    assert "id-token: write" in caller
    assert 'GITHUB_REF" != "refs/heads/main"' in caller
    assert "OPENCODE_REPOSITORY_DISPATCH_TARGETS" in caller
    assert "PR_REVIEW_MERGE_TOKEN" in caller
    assert "OPENCODE_APPROVE_TOKEN" in caller
    assert "persist-credentials: false" in caller
    assert "inputs.dry_run" not in caller
    assert "github.token" not in caller
    assert "MUTATION_CREDENTIAL_AVAILABLE: ${{ secrets.PR_REVIEW_MERGE_TOKEN != '' ||" in caller
    assert "--connect-timeout 10" in caller
    assert "--max-time 30" in caller
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


def test_each_mutating_dispatch_fails_closed_without_a_scheduler_credential() -> None:
    """Review and repair dispatches emit the same typed credential failure."""

    caller = _read(CALLER)
    availability = (
        "MUTATION_CREDENTIAL_AVAILABLE: ${{ secrets.PR_REVIEW_MERGE_TOKEN != '' ||"
    )
    guard = 'if [ "$MUTATION_CREDENTIAL_AVAILABLE" != "true" ]; then'
    diagnostic = (
        "::error::An established scheduler mutation credential or exchanged "
        "OpenCode app token is required."
    )

    assert caller.count(availability) == 2
    assert caller.count(guard) == 2
    assert caller.count(diagnostic) == 2
    review_dispatch = caller.split(
        "      - name: Dispatch one missing stacked-PR review", 1
    )[1].split("      - name: Dispatch one dependency-safe review repair", 1)[0]
    assert review_dispatch.index(guard) < review_dispatch.index(
        "python3 scripts/ci/pr_review_merge_scheduler.py"
    )


def test_stack_driver_is_product_neutral_and_one_shot_is_absent() -> None:
    """LineageWeave identity and PR numbers remain in the thin caller only."""

    driver = _read(STACK_DRIVER)
    merge_driver = _read(MERGE_DRIVER)
    assert "ContextualWisdomLab/LineageWeave" not in driver
    assert "ContextualWisdomLab/LineageWeave" not in merge_driver
    for number in ("258", "260", "261", "262", "263", "264"):
        assert re.search(rf"(?<![0-9]){number}(?![0-9])", driver) is None
    assert "expected parent head" in driver
    assert "max_dispatches != 1" in driver
    assert not ONE_SHOT.exists()


def test_lineageweave_doctoring_preserves_operational_boundaries() -> None:
    """Doctoring retains target, credential, stack, and approval rules."""

    doctoring = _read(DOCTORING)

    for phrase in (
        "ContextualWisdomLab/LineageWeave",
        "#258 → #260 → #261 → #262 → #263 → #264",
        "OPENCODE_REPOSITORY_DISPATCH_TARGETS",
        "independent non-author approval",
        "NVIDIA_NIM_API_KEY",
        "COPILOT_GITHUB_TOKEN",
        "id-token: write",
        "two-hour same-head retry floor",
        "root-cause analysis",
        "remediation feasibility",
        "protected-main operational acceptance",
        "`queue: max` is valid",
        "APA 7th references",
    ):
        assert phrase in doctoring
    assert "unsupported concurrency key" not in doctoring


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
    """Caller, driver, tests, and doctoring edits rerun the focused gate."""

    quality = _read(QUALITY_WORKFLOW)
    owned_paths = (
        ".github/workflows/lineageweave-hourly-review-repair.yml",
        ".github/workflows/lineageweave-hourly-review-repair-quality.yml",
        "scripts/ci/pr_review_fix_scheduler.py",
        "scripts/ci/pr_review_fix_stack_scheduler.py",
        "scripts/ci/pr_review_merge_scheduler.py",
        "tests/test_pr_review_fix_stack_scheduler.py",
        "tests/test_pr_review_fix_scheduler.py",
        "tests/test_pr_review_merge_scheduler.py",
        "tests/test_lineageweave_hourly_review_caller.py",
        "docs/doctoring/lineageweave-hourly-review-caller.md",
        "docs/doctoring/lineageweave-buyer-surface-opencode-incident.md",
        "requirements-opencode-review-ci-hashes.txt",
    )

    assert "\npermissions:\n  contents: read\n" in quality
    assert "\n  push:" not in quality
    assert "cancel-in-progress: true" in quality
    assert "lineageweave-hourly-review-quality-${{ github.event.pull_request.head.repo.full_name }}-${{ github.event.pull_request.head.ref }}" in quality
    assert "persist-credentials: false" in quality
    assert "fetch-depth: 0" in quality
    assert "--require-hashes" in quality
    assert "tests/test_pr_review_fix_stack_scheduler.py" in quality
    assert "tests/test_pr_review_fix_scheduler.py" in quality
    assert "tests/test_pr_review_merge_scheduler.py" in quality
    assert "--fail-under=100" in quality
    assert "interrogate -vv --fail-under 100" in quality
    assert "python -m compileall -q \\" in quality
    assert "git diff --check" in quality
    assert 'git diff --check "$BASE_SHA...$HEAD_SHA"' in quality
    for path in owned_paths:
        assert quality.count(f"      - {path}") == 1
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
