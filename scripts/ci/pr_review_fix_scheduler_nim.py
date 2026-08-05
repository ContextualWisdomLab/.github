#!/usr/bin/env python3
"""Run the central PR repair scheduler with the NVIDIA NIM autofix worker."""

from __future__ import annotations

from pathlib import Path
import sys

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPOSITORY_ROOT))

from scripts.ci import pr_review_fix_scheduler as scheduler  # noqa: E402

NIM_AUTOFIX_WORKFLOW = "nvidia-nim-pr-review-autofix.yml"
NIM_AUTOFIX_EVENT_TYPE = "nvidia-nim-pr-review-autofix"


def _normalized_argv(argv: list[str]) -> list[str]:
    """Return scheduler arguments pinned to the NVIDIA NIM worker contract."""

    normalized = list(argv)
    if "--autofix-workflow" not in normalized:
        normalized.extend(["--autofix-workflow", NIM_AUTOFIX_WORKFLOW])
    return normalized


def main(argv: list[str]) -> int:
    """Run the shared scheduler with temporary NVIDIA NIM dispatch constants."""

    original_workflow = scheduler.DEFAULT_AUTOFIX_WORKFLOW
    original_event_type = scheduler.AUTOFIX_REPOSITORY_DISPATCH_TYPE
    try:
        scheduler.DEFAULT_AUTOFIX_WORKFLOW = NIM_AUTOFIX_WORKFLOW
        scheduler.AUTOFIX_REPOSITORY_DISPATCH_TYPE = NIM_AUTOFIX_EVENT_TYPE
        return scheduler.main(_normalized_argv(argv))
    finally:
        scheduler.DEFAULT_AUTOFIX_WORKFLOW = original_workflow
        scheduler.AUTOFIX_REPOSITORY_DISPATCH_TYPE = original_event_type


if __name__ == "__main__":  # pragma: no cover - exercised through the workflow
    raise SystemExit(main(sys.argv[1:]))
