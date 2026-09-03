"""Live post-apply verification contracts for reviewed repository labels."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ci" / "reconcile_repository_labels.py"
SPEC = importlib.util.spec_from_file_location("reconcile_repository_labels", SCRIPT)
assert SPEC and SPEC.loader
LABELS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LABELS)


def assignment() -> dict[str, object]:
    """Return one reviewed label assignment."""

    return {"repository": "Repo", "issue": 1, "type": "documentation"}


def type_map() -> dict[str, str]:
    """Return a minimal managed label universe."""

    return {"bug": "bug", "documentation": "documentation"}


def test_verify_assignment_accepts_only_exact_managed_postcondition(monkeypatch) -> None:
    """Unmanaged labels survive while the one desired managed label must be exact."""

    monkeypatch.setattr(
        LABELS,
        "_gh_api",
        lambda *args, **kwargs: json.dumps(
            {
                "labels": [
                    {"name": "status: needs-review"},
                    {"name": "documentation"},
                ]
            }
        ),
    )
    LABELS.verify_assignment(assignment(), type_map())

    monkeypatch.setattr(
        LABELS,
        "_gh_api",
        lambda *args, **kwargs: json.dumps({"labels": [{"name": "bug"}]}),
    )
    with pytest.raises(RuntimeError, match="managed labels did not converge"):
        LABELS.verify_assignment(assignment(), type_map())


def test_main_verify_only_uses_read_only_verifier(monkeypatch, tmp_path: Path) -> None:
    """Verify-only mode checks assignments without entering mutation logic."""

    taxonomy = tmp_path / "taxonomy.json"
    taxonomy.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "type": {"documentation": "documentation"},
                "assignments": [assignment()],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("GH_TOKEN", "token")
    monkeypatch.setattr(
        LABELS,
        "parse_args",
        lambda: argparse.Namespace(
            taxonomy=taxonomy,
            validate_only=False,
            verify_only=True,
            repository=[],
        ),
    )
    seen = []
    monkeypatch.setattr(
        LABELS,
        "verify_assignment",
        lambda item, mappings: seen.append(item["repository"]),
    )
    monkeypatch.setattr(
        LABELS,
        "reconcile_assignment",
        lambda *args: pytest.fail("mutation path used in verify-only mode"),
    )

    assert LABELS.main() == 0
    assert seen == ["Repo"]
