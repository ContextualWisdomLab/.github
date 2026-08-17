"""Contract tests for kaefa's bounded hourly review-repair caller."""

from pathlib import Path


CALLER = Path(".github/workflows/kaefa-hourly-review-repair.yml")
DOCTORING = Path("docs/doctoring/kaefa-hourly-review-caller.md")
QUALITY_WORKFLOW = Path(".github/workflows/hourly-nvidia-nim-review-repair.yml")
SCHEDULER = Path(".github/workflows/pr-review-fix-scheduler.yml")


def _read(path: Path) -> str:
    """Return one repository contract file as UTF-8 text."""
    return path.read_text(encoding="utf-8")


def _yaml_path_entries(block: str) -> set[str]:
    """Return dashed YAML path entries from one trigger or compileall block."""
    entries: set[str] = set()
    for raw_line in block.splitlines():
        stripped = raw_line.strip()
        if stripped.startswith("- "):
            entries.add(stripped[2:].strip())
        elif stripped.startswith("tests/") or stripped.startswith("scripts/"):
            entries.add(stripped.rstrip(" \\"))
    return entries


def _trigger_path_block(quality: str, trigger: str) -> str:
    """Return the dashed path list under one named workflow trigger."""
    marker = f"  {trigger}:\n    paths:\n"
    start = quality.index(marker) + len(marker)
    lines: list[str] = []
    for line in quality[start:].splitlines():
        if line.startswith("      - "):
            lines.append(line)
            continue
        if line.strip() == "":
            continue
        break
    return "\n".join(lines)


def _compileall_block(quality: str) -> str:
    """Return the compileall argument list from the focused quality job."""
    marker = "python -m compileall -q \\"
    start = quality.index(marker)
    remainder = quality[start:]
    end = remainder.find("\n          git ")
    return remainder if end < 0 else remainder[:end]


def test_kaefa_caller_is_hourly_bounded_and_non_cancelling() -> None:
    """kaefa receives one realistic item-fit repair without cancellation."""
    caller = _read(CALLER)

    assert 'cron: "3 * * * *"' in caller
    assert "group: kaefa-hourly-review-repair" in caller
    assert "cancel-in-progress: false" in caller
    assert "uses: ./.github/workflows/pr-review-fix-scheduler.yml" in caller
    assert "target_repository: ContextualWisdomLab/kaefa" in caller
    assert "base_branch: develop" in caller
    assert 'max_prs: "50"' in caller
    assert 'max_dispatches: "1"' in caller
    assert 'retry_hours: "2"' in caller


def test_kaefa_caller_preserves_oidc_and_explicit_secret_scope() -> None:
    """The queue scanner maps established credentials without model secrets."""
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


def test_kaefa_target_is_not_hard_coded_in_shared_scheduler() -> None:
    """Product identity remains in the thin caller rather than the engine."""
    assert "ContextualWisdomLab/kaefa" not in _read(SCHEDULER)


def test_kaefa_doctoring_records_efa_activation_and_credentials() -> None:
    """Operators retain target-allowlist, EFA, and approval prerequisites."""
    doctoring = _read(DOCTORING)

    for phrase in (
        "ContextualWisdomLab/kaefa",
        "OPENCODE_REPOSITORY_DISPATCH_TARGETS",
        "independent non-author approval",
        "NVIDIA_NIM_API_KEY",
        "COPILOT_GITHUB_TOKEN",
        "id-token: write",
        "two-hour same-head retry floor",
        "root-cause analysis",
        "remediation feasibility",
        "protected-develop operational acceptance",
        "APA 7th references",
        "ContextualWisdomLab/kaefa#78",
        "ContextualWisdomLab/kaefa#75",
        "ContextualWisdomLab/kaefa#60",
        "GPL-3.0",
    ):
        assert phrase in doctoring


def test_path_block_helpers_keep_trigger_and_compileall_sets_disjoint() -> None:
    """A path listed only under push or compileall must not satisfy pull_request."""
    quality = (
        "on:\n"
        "  pull_request:\n"
        "    paths:\n"
        "      - .github/workflows/kaefa-hourly-review-repair.yml\n"
        "  push:\n"
        "    paths:\n"
        "      - docs/doctoring/kaefa-hourly-review-caller.md\n"
        "          python -m compileall -q \\\n"
        "            tests/test_kaefa_hourly_review_caller.py\n"
        "          git diff --check\n"
    )

    pull_request_paths = _yaml_path_entries(_trigger_path_block(quality, "pull_request"))
    push_paths = _yaml_path_entries(_trigger_path_block(quality, "push"))
    compileall_paths = _yaml_path_entries(_compileall_block(quality))

    assert pull_request_paths == {".github/workflows/kaefa-hourly-review-repair.yml"}
    assert push_paths == {"docs/doctoring/kaefa-hourly-review-caller.md"}
    assert compileall_paths == {"tests/test_kaefa_hourly_review_caller.py"}
    assert "docs/doctoring/kaefa-hourly-review-caller.md" not in pull_request_paths
    assert ".github/workflows/kaefa-hourly-review-repair.yml" not in compileall_paths


def test_focused_quality_workflow_tracks_kaefa_contracts() -> None:
    """Caller, test, and doctoring edits always rerun the focused gate."""
    quality = _read(QUALITY_WORKFLOW)
    pull_request_paths = _yaml_path_entries(_trigger_path_block(quality, "pull_request"))
    push_paths = _yaml_path_entries(_trigger_path_block(quality, "push"))
    compileall_paths = _yaml_path_entries(_compileall_block(quality))
    caller = ".github/workflows/kaefa-hourly-review-repair.yml"
    doctoring = "docs/doctoring/kaefa-hourly-review-caller.md"
    contract = "tests/test_kaefa_hourly_review_caller.py"

    assert caller in pull_request_paths
    assert doctoring in pull_request_paths
    assert contract in pull_request_paths
    assert caller in push_paths
    assert doctoring in push_paths
    assert contract in compileall_paths
    assert caller not in compileall_paths
    assert doctoring not in compileall_paths
