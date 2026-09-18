"""Regression coverage for queue-health repository identity admission."""

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts/ci/actions_queue_health_core.py"
SPEC = importlib.util.spec_from_file_location("actions_queue_health_core_identity", MODULE_PATH)
assert SPEC and SPEC.loader
queue_health = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(queue_health)


@pytest.mark.parametrize(
    "repository",
    [
        "ContextualWisdomLab/repository.",
        "ContextualWisdomLab/repo..name",
        "ContextualWisdomLab/..",
        "ContextualWisdomLab/.",
    ],
)
def test_load_allowlist_rejects_noncanonical_repository_identity(
    tmp_path: Path, repository: str
) -> None:
    """Reject non-canonical repository components through the production allowlist path."""
    allowlist = tmp_path / "repositories.json"
    allowlist.write_text(
        json.dumps({"repositories": [repository]}),
        encoding="utf-8",
    )

    with pytest.raises(queue_health.QueueHealthError, match="invalid repository identifier"):
        queue_health.load_allowlist(allowlist)
