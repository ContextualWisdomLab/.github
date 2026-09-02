"""Fail-closed contracts for Noema model-call policy ownership."""

from pathlib import Path


_SOURCE = Path("scripts/ci/noema_review_gate.py")


def test_noema_has_no_repository_fixed_wall_clock_deadline() -> None:
    """Keep model inference free of caller-authored elapsed-time termination."""
    source = _SOURCE.read_text(encoding="utf-8")
    assert "NOEMA_REPAIR_DEADLINE_SECONDS" not in source
    assert "_repair_wall_clock_deadline(" not in source
    assert "NoemaRepairDeadlineExceeded" not in source
    assert "signal.setitimer" not in source


def test_noema_has_no_caller_authored_model_retry() -> None:
    """Malformed/transport evidence fails closed instead of authorizing another inference."""
    source = _SOURCE.read_text(encoding="utf-8")
    assert "is_retry" not in source
    assert "repair_error" not in source
    assert "StaleHeadDuringRepairRetryError" not in source
    assert "return call_llm(" not in source


def test_noema_does_not_assign_a_sampling_temperature() -> None:
    """Noema declares output structure but delegates sampling policy to contextual-orchestrator."""
    source = _SOURCE.read_text(encoding="utf-8")
    assert '"temperature"' not in source
