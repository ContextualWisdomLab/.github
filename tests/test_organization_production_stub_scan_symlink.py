from __future__ import annotations

from pathlib import Path

import pytest

from scripts.ci import organization_production_stub_scan as scan


def test_symbolic_link_runtime_source_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reject a tracked runtime symlink before any target metadata or content access."""
    outside_source = tmp_path.parent / f"{tmp_path.name}-outside.py"
    outside_source.write_text("def outside():\n    return 1\n", encoding="utf-8")
    relative_path = Path("src/service.py")
    source_path = tmp_path / relative_path
    source_path.parent.mkdir(parents=True)
    source_path.symlink_to(outside_source)

    original_is_file = Path.is_file

    def guarded_is_file(self: Path) -> bool:
        if self.is_symlink():
            raise AssertionError("is_file followed a symbolic link")
        return original_is_file(self)

    monkeypatch.setattr(Path, "is_file", guarded_is_file)

    findings, errors = scan.scan_changed_paths(tmp_path, [relative_path])

    assert findings == []
    assert errors == ["src/service.py is a symbolic link and cannot be scanned"]
    assert scan.is_inventory_candidate(tmp_path, relative_path) is True


def test_parent_directory_symlink_fails_closed(tmp_path: Path) -> None:
    """Reject a runtime path whose parent directory is a symbolic link."""
    outside_directory = tmp_path.parent / f"{tmp_path.name}-outside"
    outside_directory.mkdir()
    (outside_directory / "service.py").write_text(
        "def outside():\n    return 1\n", encoding="utf-8"
    )
    (tmp_path / "src").symlink_to(outside_directory)

    findings, errors = scan.scan_changed_paths(tmp_path, [Path("src/service.py")])

    assert findings == []
    assert errors == ["src/service.py is a symbolic link and cannot be scanned"]


def test_regular_runtime_file_remains_an_inventory_candidate(tmp_path: Path) -> None:
    """Keep ordinary files on the scan path after the symlink gate."""
    relative_path = Path("src/service.py")
    source_path = tmp_path / relative_path
    source_path.parent.mkdir(parents=True)
    source_path.write_text("def ok():\n    return 1\n", encoding="utf-8")

    assert scan.first_symlink_on_relative_path(tmp_path, relative_path) is None
    assert scan.is_inventory_candidate(tmp_path, relative_path) is True
    assert scan.is_inventory_candidate(tmp_path, Path("src/missing.py")) is False
