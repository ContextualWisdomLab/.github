"""Contract tests for Noema model-call timeout ownership."""

from pathlib import Path


_SOURCE = Path("scripts/ci/noema_review_gate.py")


def test_noema_repair_has_no_repository_fixed_wall_clock_deadline() -> None:
    """Keep model inference free of caller-authored elapsed-time termination."""
    source = _SOURCE.read_text(encoding="utf-8")
    assert "NOEMA_REPAIR_DEADLINE_SECONDS" not in source
    assert "_repair_wall_clock_deadline(" not in source
    assert "NoemaRepairDeadlineExceeded" not in source
    assert "signal.setitimer" not in source


def test_noema_repair_retry_cardinality_remains_bounded() -> None:
    """Removing the clock cap must not introduce an unbounded caller retry loop."""
    source = _SOURCE.read_text(encoding="utf-8")
    assert "if is_retry:" in source
    assert source.count("is_retry=True") == 1
