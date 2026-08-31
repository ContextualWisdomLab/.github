"""Runtime-budget contracts for hourly review-repair schedulers."""

from pathlib import Path


REUSABLE = Path(".github/workflows/pr-review-fix-scheduler.yml")
CLEARFOLIO = Path(".github/workflows/clearfolio-hourly-review-repair.yml")
DISKSAGE = Path(".github/workflows/disksage-hourly-review-repair.yml")
QUALITY = Path(".github/workflows/hourly-nvidia-nim-review-repair.yml")


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
    """Clearfolio and DiskSage preserve the non-cancelling product lease."""
    for caller_path in (CLEARFOLIO, DISKSAGE):
        caller = _read(caller_path)
        assert "cancel-in-progress: false" in caller
        assert "cancel-in-progress: true" not in caller


def test_disksage_caller_grants_oidc_permission_to_reusable_scheduler() -> None:
    """The called scheduler must be able to exchange its OpenCode OIDC token."""
    caller = _read(DISKSAGE)
    job = caller.split("  dispatch-review-repair:\n", maxsplit=1)[1]

    assert "    permissions:\n      contents: read\n      id-token: write\n" in job


def test_quality_gate_tracks_runtime_budget_contract() -> None:
    """Runtime-budget changes always execute the exact-head focused gate."""
    quality = _read(QUALITY)

    assert quality.count("tests/test_hourly_scheduler_runtime_budget.py") == 3
