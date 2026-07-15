"""Tests for package and virtual-workspace Rust coverage baselines."""

from pathlib import Path

import pytest

from scripts.ci import rust_coverage_threshold as threshold


def test_package_metadata_takes_precedence() -> None:
    """A concrete package may override a workspace-wide default."""
    document = {
        "package": {"metadata": {"opencode": {"coverage": {"minimum_lines": 92}}}},
        "workspace": {"metadata": {"opencode": {"coverage": {"minimum_lines": 88}}}},
    }

    assert threshold.resolve_minimum_lines(document) == 92.0


def test_virtual_workspace_metadata_is_supported(tmp_path: Path) -> None:
    """A root manifest without a package table can own the workspace baseline."""
    manifest = tmp_path / "Cargo.toml"
    manifest.write_text(
        '[workspace]\nmembers = ["crates/core"]\n\n'
        "[workspace.metadata.opencode.coverage]\nminimum_lines = 90\n",
        encoding="utf-8",
    )

    assert threshold.read_minimum_lines(manifest) == 90.0


@pytest.mark.parametrize("value", [True, "90", -1, 101])
def test_invalid_thresholds_fail_closed(value: object) -> None:
    """Non-numeric and out-of-range baselines cannot weaken the coverage gate."""
    document = {
        "workspace": {"metadata": {"opencode": {"coverage": {"minimum_lines": value}}}}
    }

    with pytest.raises(ValueError, match="workspace.metadata.opencode.coverage.minimum_lines"):
        threshold.resolve_minimum_lines(document)


def test_missing_metadata_keeps_central_default() -> None:
    """No declaration remains distinguishable from an explicit zero threshold."""
    assert threshold.resolve_minimum_lines({"workspace": {}}) is None
    assert threshold.resolve_minimum_lines(
        {"workspace": {"metadata": {"opencode": {"coverage": {"minimum_lines": 0}}}}}
    ) == 0.0
