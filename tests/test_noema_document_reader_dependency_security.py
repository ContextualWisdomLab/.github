"""Keep the Noema document reader above known vulnerable transitive releases."""

from __future__ import annotations

import json
from pathlib import Path


LOCK_FILE = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "ci"
    / "noema-document-reader"
    / "package-lock.json"
)


def _version_tuple(package_name: str) -> tuple[int, ...]:
    """Return the numeric release tuple recorded for one locked package."""
    lock_data = json.loads(LOCK_FILE.read_text(encoding="utf-8"))
    package_data = lock_data["packages"][f"node_modules/{package_name}"]
    return tuple(int(part) for part in package_data["version"].split("."))


def test_document_reader_transitives_include_security_fixes() -> None:
    """Reject releases affected by the September 2026 URI and IP advisories."""
    assert _version_tuple("fast-uri") >= (3, 1, 8)
    assert _version_tuple("ip-address") >= (10, 7, 2)
