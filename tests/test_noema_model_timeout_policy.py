"""Regression contract for Noema model-execution timeout ownership."""

from __future__ import annotations

import re
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
NOEMA_WORKFLOW_PATH = REPOSITORY_ROOT / ".github" / "workflows" / "noema-review.yml"


def _noema_model_job_text() -> str:
    """Return the Noema model-bearing job from the trusted workflow source."""
    workflow_text = NOEMA_WORKFLOW_PATH.read_text(encoding="utf-8")
    return workflow_text.split("  noema-review:\n", 1)[1]


def test_noema_model_job_has_no_elapsed_time_termination() -> None:
    """Keep model reasoning free of a GitHub job wall-clock termination policy."""
    model_job_text = _noema_model_job_text()

    assert "Prepare Noema model verdict" in model_job_text
    assert re.search(
        r"^    timeout-minutes:\s*\d+\s*$", model_job_text, flags=re.MULTILINE
    ) is None, (
        "Noema model execution must not be terminated by elapsed time; user cancel, "
        "provider termination, and an explicitly configured contextual-orchestrator "
        "admin timeout are the only timeout authorities."
    )
