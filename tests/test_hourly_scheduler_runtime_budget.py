"""Runtime-budget contracts for hourly review-repair schedulers."""

from pathlib import Path


REUSABLE = Path(".github/workflows/pr-review-fix-scheduler.yml")
# Clearfolio and DiskSage (like all 18 former per-repository callers) are now
# both resolved from the one consolidated caller file.
CONSOLIDATED_CALLER = Path(".github/workflows/hourly-review-repair.yml")
QUALITY = Path(".github/workflows/hourly-nvidia-nim-review-repair.yml")
REPLACEMENT_QUALITY = Path(
    ".github/workflows/contextual-orchestrator-review-repair-quality.yml"
)


def _read(path: Path) -> str:
    """Return one workflow as UTF-8 text."""
    return path.read_text(encoding="utf-8")


def test_queue_scanner_has_a_bounded_superseding_runtime() -> None:
    """A fresh read-only scan supersedes a stale scan and cannot run forever."""
    reusable = _read(REUSABLE)
    job = reusable.split("  dispatch-review-fixes:\n", maxsplit=1)[1]

    assert "cancel-in-progress: true" in reusable
    assert "    timeout-minutes: 35\n" in job
    assert "separately dispatched per-PR OpenCode worker" in reusable


def test_product_callers_do_not_cancel_an_in_flight_rca() -> None:
    """Every consolidated product caller preserves the non-cancelling lease."""
    caller = _read(CONSOLIDATED_CALLER)

    assert "cancel-in-progress: false" in caller
    assert "cancel-in-progress: true" not in caller


def test_disksage_caller_grants_oidc_permission_to_reusable_scheduler() -> None:
    """The called scheduler must be able to exchange its OpenCode OIDC token."""
    caller = _read(CONSOLIDATED_CALLER)
    job = caller.split("  dispatch-review-repair:\n", maxsplit=1)[1]

    assert "    permissions:\n      contents: read\n      id-token: write\n" in job


def test_quality_gate_tracks_runtime_budget_contract() -> None:
    """Runtime-budget changes always execute the exact-head focused gate."""
    quality = _read(QUALITY)

    assert quality.count("tests/test_hourly_scheduler_runtime_budget.py") == 3


def test_quality_gate_close_event_retires_prior_pr_run_without_runner() -> None:
    """Closing a PR must supersede queued work without allocating a cleanup runner."""
    quality = _read(QUALITY)
    pull_request_trigger = quality.split("  pull_request:\n", maxsplit=1)[1].split(
        "  push:\n", maxsplit=1
    )[0]
    contract_job = quality.split("  contract:\n", maxsplit=1)[1]

    assert "    types: [opened, synchronize, reopened, closed]\n" in pull_request_trigger
    assert (
        "  group: contextual-orchestrator-review-repair-quality-"
        "${{ github.event.pull_request.number || github.ref }}\n"
    ) in quality
    assert "  cancel-in-progress: true\n" in quality
    assert (
        "    if: ${{ github.event_name != 'pull_request' || github.event.action != 'closed' }}\n"
        in contract_job
    )


def test_quality_gate_push_runs_only_on_the_default_branch() -> None:
    """PR branch pushes rely on pull_request; push validates merged main."""
    quality = _read(QUALITY)
    push_trigger = quality.split("  push:\n", maxsplit=1)[1].split(
        "\nconcurrency:\n", maxsplit=1
    )[0]

    assert push_trigger.startswith("    branches: [main]\n")
    assert push_trigger.count("branches:") == 1


def test_review_repair_quality_workflow_has_truthful_identity() -> None:
    """Keep the stable workflow ID while retiring its direct-NIM identity."""
    assert QUALITY.is_file()
    assert not REPLACEMENT_QUALITY.exists()

    quality = _read(QUALITY)
    assert quality.startswith("name: Contextual Orchestrator Review Repair Quality CI\n")
    assert "schedule:" not in quality
    assert "name: Hourly NVIDIA NIM Review Repair" not in quality
    assert "Hourly cadence, immutable source, NIM credential, and conflict scope" not in quality
    assert "registry identity is updated in place" in quality
    assert ".github/workflows/pr-review-autofix.yml" in quality
    assert "contextual-orchestrator/orchestrator/free" in quality
    assert "tests/test_pr_review_autofix_nvidia_nim_contract.py" in quality
