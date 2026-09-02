#!/usr/bin/env python3
"""Normalize OpenCode review output, including explicit fail-closed non-conclusions.

The full control-verdict normalizer remains in ``opencode_review_normalize_output_core``.
This thin compatibility surface adds one transport-only state: an exact current-run
``opencode-review-needs-info`` marker with no control block is preserved unchanged so
the terminal approval gate can return ``NO_CONCLUSION``. It never becomes APPROVE or
REQUEST_CHANGES.
"""

from __future__ import annotations

import sys
from pathlib import Path

try:
    import opencode_review_normalize_output_core as _core
except ModuleNotFoundError:  # pragma: no cover - package import path
    from scripts.ci import opencode_review_normalize_output_core as _core

# Source-contract tests and callers continue to receive the original module object,
# including repair_approval_summary and every other public helper used by gates/tests.
_original_main = _core.main


def _is_current_run_needs_info(argv: list[str]) -> bool:
    """Return whether argv names the one exact transport-only non-conclusion body."""
    if len(argv) != 5:
        return False
    _program, head_sha, run_id, run_attempt, output_path = argv
    if not head_sha or not run_id or not run_attempt:
        return False
    try:
        text = Path(output_path).read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return False
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    sentinel = (
        f"<!-- opencode-review-gate head_sha={head_sha} "
        f"run_id={run_id} run_attempt={run_attempt} -->"
    )
    marker = (
        f"<!-- opencode-review-needs-info head_sha={head_sha} "
        f"run_id={run_id} run_attempt={run_attempt} -->"
    )
    return lines == [sentinel, marker] and "opencode-review-control-v1" not in text


def main(argv: list[str]) -> int:
    """Preserve a validated non-conclusion; delegate all control verdicts unchanged."""
    if _is_current_run_needs_info(argv):
        return 0
    return _original_main(argv)


_core.main = main

if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv))

# When imported, expose the unchanged core module so monkeypatching/tests/callers keep
# the same module-global semantics rather than operating through copied function globals.
sys.modules[__name__] = _core
