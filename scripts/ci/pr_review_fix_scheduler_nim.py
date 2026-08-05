#!/usr/bin/env python3
"""Run the central PR repair scheduler with the NVIDIA NIM autofix worker."""

from __future__ import annotations

import sys

try:
    import pr_review_fix_scheduler as scheduler
except ModuleNotFoundError:
    from scripts.ci import pr_review_fix_scheduler as scheduler

NIM_AUTOFIX_WORKFLOW = "nvidia-nim-pr-review-autofix.yml"
NIM_AUTOFIX_EVENT_TYPE = "nvidia-nim-pr-review-autofix"


def _normalized_argv(argv: list[str]) -> list[str]:
    """Return scheduler arguments pinned to the NVIDIA NIM worker contract."""

    normalized = list(argv)
    if "--autofix-workflow" not in normalized:
        normalized.extend(["--autofix-workflow", NIM_AUTOFIX_WORKFLOW])
    return normalized


def main(argv: list[str]) -> int:
    """Apply NVIDIA NIM dispatch constants and run the shared scheduler."""

    scheduler.DEFAULT_AUTOFIX_WORKFLOW = NIM_AUTOFIX_WORKFLOW
    scheduler.AUTOFIX_REPOSITORY_DISPATCH_TYPE = NIM_AUTOFIX_EVENT_TYPE
    return scheduler.main(_normalized_argv(argv))


if __name__ == "__main__":  # pragma: no cover - exercised through the workflow
    raise SystemExit(main(sys.argv[1:]))
