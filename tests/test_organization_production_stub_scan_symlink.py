from __future__ import annotations

from pathlib import Path

from scripts.ci import organization_production_stub_scan as scan


def test_symbolic_link_runtime_source_fails_closed(tmp_path: Path) -> None:
    """Reject a tracked runtime symlink before any target metadata or content access."""
    outside_source = tmp_path.parent / f"{tmp_path.name}-outside.py"
    outside_source.write_text("def outside():\n    return 1\n", encoding="utf-8")
    relative_path = Path("src/service.py")
    source_path = tmp_path / relative_path
    source_path.parent.mkdir(parents=True)
    source_path.symlink_to(outside_source)

    findings, errors = scan.scan_changed_paths(tmp_path, [relative_path])

    assert findings == []
    assert errors == ["src/service.py is a symbolic link and cannot be scanned"]
