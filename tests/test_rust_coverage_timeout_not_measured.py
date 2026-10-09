"""A Rust coverage run that only exceeds the per-command cap is recorded as not measured."""

from __future__ import annotations

import subprocess
from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/opencode-review-dispatch.yml"


def _classifier() -> str:
    text = WORKFLOW.read_text(encoding="utf-8")
    start = text.index("          record_command_result() {")
    end = text.index("\n          }\n", start) + len("\n          }\n")
    return "\n".join(line[10:] for line in text[start:end].splitlines())


def _classify(rc: int, tolerate_timeout: bool) -> tuple[str, int, int]:
    script = (
        "set -euo pipefail\nfailures=0\nnot_measured=0\nout=\"\"\n"
        'append() { out="$out$1\n"; }\n'
        + _classifier()
        + f"\ncoverage_timeout_not_measured={int(tolerate_timeout)}\n"
        + f"record_command_result {rc}\n"
        + 'printf "%s|%s|%s" "$out" "$failures" "$not_measured"\n'
    )
    result = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=True)
    text, failures, not_measured = result.stdout.rsplit("|", 2)
    return text, int(failures), int(not_measured)


def test_success_passes() -> None:
    assert _classify(0, True) == ("- Result: PASS\n", 0, 0)


def test_timeout_under_rust_coverage_is_not_measured() -> None:
    text, failures, not_measured = _classify(124, True)
    assert text.startswith("- Result: NOT MEASURED")
    assert (failures, not_measured) == (0, 1)


def test_timeout_elsewhere_still_fails() -> None:
    assert _classify(124, False) == ("- Result: FAIL (exit 124)\n", 1, 0)


def test_kill_or_test_failure_still_fails_under_rust_coverage() -> None:
    assert _classify(137, True)[1:] == (1, 0)
    assert _classify(1, True)[1:] == (1, 0)


def test_only_rust_coverage_calls_tolerate_the_timeout() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert text.count("coverage_timeout_not_measured=1") == 1
    assert text.count("coverage_timeout_not_measured=0") == 2  # init + reset after Rust
    rust = text.split("coverage_timeout_not_measured=1", 1)[1].split("coverage_timeout_not_measured=0", 1)[0]
    assert "cargo llvm-cov --workspace" in rust
    assert "cargo llvm-cov --manifest-path" in rust
