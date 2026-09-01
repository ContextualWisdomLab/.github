"""Regression coverage for Noema repair wall-clock alarm ownership."""

import pytest

from scripts.ci import noema_review_gate as gate


def test_repair_deadline_refuses_to_clobber_an_existing_process_alarm(monkeypatch) -> None:
    """A repair deadline must fail closed before replacing another alarm owner."""
    monkeypatch.setattr(gate.signal, "getitimer", lambda _kind: (5.0, 0.0))
    set_calls: list[tuple[object, ...]] = []
    monkeypatch.setattr(
        gate.signal,
        "setitimer",
        lambda *args: set_calls.append(args),
    )

    with pytest.raises(
        RuntimeError,
        match="refused to overwrite an active process alarm",
    ):
        with gate._repair_wall_clock_deadline(0.05):
            pytest.fail("deadline context must not run while another alarm is active")

    assert set_calls == []
