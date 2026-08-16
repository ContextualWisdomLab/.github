"""Fail-first contracts for fatal-provider process-group termination."""

from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_fatal_provider_attempt_owns_and_terminates_its_process_group() -> None:
    """Fatal-provider cleanup must signal the dedicated attempt process group."""
    launcher = (
        REPO_ROOT / "scripts" / "ci" / "run_opencode_review_model_pool.sh"
    ).read_text(encoding="utf-8")

    assert 'setsid timeout --kill-after=30s "${run_timeout_seconds}s"' in launcher
    assert 'kill -TERM -- "-$opencode_pid"' in launcher
    assert 'kill -0 -- "-$opencode_pid"' in launcher
    assert 'kill -KILL -- "-$opencode_pid"' in launcher
    assert 'kill "$opencode_pid"' not in launcher
    assert 'kill -9 "$opencode_pid"' not in launcher
