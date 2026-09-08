"""Focused convergence regressions for repository label reconciliation."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ci" / "reconcile_repository_labels.py"
SPEC = importlib.util.spec_from_file_location("reconcile_repository_labels", SCRIPT)
assert SPEC and SPEC.loader
LABELS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LABELS)


def test_existing_desired_label_does_not_get_readded_while_obsolete_type_is_removed(
    monkeypatch,
) -> None:
    """A mixed managed state removes only the obsolete label."""

    calls: list[tuple[str, str, object, bool]] = []
    reads = iter(
        [
            json.dumps(
                {
                    "labels": [
                        {"name": "documentation"},
                        {"name": "bug"},
                        {"name": "status: needs-review"},
                    ]
                }
            ),
            json.dumps(
                {
                    "labels": [
                        {"name": "documentation"},
                        {"name": "status: needs-review"},
                    ]
                }
            ),
        ]
    )

    def gh_api(method, endpoint, body=None, allow_not_found=False):
        calls.append((method, endpoint, body, allow_not_found))
        if method == "GET":
            return next(reads)
        return ""

    monkeypatch.setattr(LABELS, "_gh_api", gh_api)

    LABELS.reconcile_assignment(
        {"repository": "Repo", "issue": 1, "type": "documentation"},
        {"bug": "bug", "documentation": "documentation"},
    )

    assert [call[0] for call in calls] == ["GET", "DELETE", "GET"]
    assert calls[1][1].endswith("/labels/bug")
