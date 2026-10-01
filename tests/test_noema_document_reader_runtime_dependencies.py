"""Security contracts for Noema document-reader runtime dependencies."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


LOCK_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "ci"
    / "noema-document-reader"
    / "package-lock.json"
)


@pytest.mark.parametrize(
    ("package_name", "safe_version"),
    (("fast-uri", "3.1.8"), ("ip-address", "10.7.1")),
)
def test_noema_document_reader_uses_exclusive_safe_runtime_dependency(
    package_name: str, safe_version: str
) -> None:
    """The lock must contain one exact non-vulnerable transitive package."""
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    package_path = f"node_modules/{package_name}"
    matching_packages = {
        path: metadata
        for path, metadata in lock["packages"].items()
        if path == package_path or path.endswith(f"/{package_path}")
    }

    assert list(matching_packages) == [package_path]
    assert matching_packages[package_path]["version"] == safe_version
