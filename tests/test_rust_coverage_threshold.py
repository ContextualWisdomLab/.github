"""Tests for package and virtual-workspace Rust coverage baselines."""

import runpy
import sys
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


def test_nested_package_inherits_nearest_workspace_baseline(tmp_path: Path) -> None:
    """A crate without a local override must use the workspace baseline."""
    workspace = tmp_path / "Cargo.toml"
    workspace.write_text(
        '[workspace]\nmembers = ["crates/core"]\n\n'
        "[workspace.metadata.opencode.coverage]\nminimum_lines = 87\n",
        encoding="utf-8",
    )
    manifest = tmp_path / "crates" / "core" / "Cargo.toml"
    manifest.parent.mkdir(parents=True)
    manifest.write_text('[package]\nname = "core"\nversion = "0.1.0"\n', encoding="utf-8")

    assert threshold.read_minimum_lines(manifest) == 87.0


def test_nested_package_override_beats_workspace_baseline(tmp_path: Path) -> None:
    """A crate-specific baseline remains stronger than inherited metadata."""
    workspace = tmp_path / "Cargo.toml"
    workspace.write_text(
        '[workspace]\nmembers = ["crates/core"]\n\n'
        "[workspace.metadata.opencode.coverage]\nminimum_lines = 87\n",
        encoding="utf-8",
    )
    manifest = tmp_path / "crates" / "core" / "Cargo.toml"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        '[package]\nname = "core"\nversion = "0.1.0"\n\n'
        "[package.metadata.opencode.coverage]\nminimum_lines = 93\n",
        encoding="utf-8",
    )

    assert threshold.read_minimum_lines(manifest) == 93.0


def test_nested_package_rejects_invalid_workspace_baseline(tmp_path: Path) -> None:
    """An inherited malformed baseline cannot silently restore the central default."""
    workspace = tmp_path / "Cargo.toml"
    workspace.write_text(
        '[workspace]\nmembers = ["crates/core"]\n\n'
        '[workspace.metadata.opencode.coverage]\nminimum_lines = "high"\n',
        encoding="utf-8",
    )
    manifest = tmp_path / "crates" / "core" / "Cargo.toml"
    manifest.parent.mkdir(parents=True)
    manifest.write_text('[package]\nname = "core"\nversion = "0.1.0"\n', encoding="utf-8")

    with pytest.raises(ValueError, match=r"workspace\.metadata\.opencode\.coverage\.minimum_lines"):
        threshold.read_minimum_lines(manifest)


@pytest.mark.parametrize("value", [True, "90", -1, 101])
def test_invalid_thresholds_fail_closed(value: object) -> None:
    """Non-numeric and out-of-range baselines cannot weaken the coverage gate."""
    document = {
        "workspace": {"metadata": {"opencode": {"coverage": {"minimum_lines": value}}}}
    }

    with pytest.raises(ValueError, match=r"workspace\.metadata\.opencode\.coverage\.minimum_lines"):
        threshold.resolve_minimum_lines(document)


def test_missing_metadata_keeps_central_default() -> None:
    """No declaration remains distinguishable from an explicit zero threshold."""
    assert threshold.resolve_minimum_lines({"workspace": {}}) is None
    assert threshold.resolve_minimum_lines(
        {"workspace": {"metadata": {"opencode": {"coverage": {"minimum_lines": 0}}}}}
    ) == 0.0


def test_cli_prints_normalized_workspace_threshold(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The trusted workflow CLI emits exactly the value passed to cargo llvm-cov."""
    manifest = tmp_path / "Cargo.toml"
    manifest.write_text(
        "[workspace.metadata.opencode.coverage]\nminimum_lines = 90.5\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(sys, "argv", ["rust_coverage_threshold.py", str(manifest)])

    assert threshold.main() == 0
    assert capsys.readouterr().out == "90.5\n"


def test_cli_reports_invalid_metadata(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Malformed repository metadata is an actionable nonzero CLI error."""
    manifest = tmp_path / "Cargo.toml"
    manifest.write_text(
        '[workspace.metadata.opencode.coverage]\nminimum_lines = "high"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(sys, "argv", ["rust_coverage_threshold.py", str(manifest)])

    with pytest.raises(SystemExit, match="2"):
        threshold.main()
    assert "must be a number from 0 to 100" in capsys.readouterr().err


def test_script_entrypoint_exits_cleanly(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The executable workflow entrypoint delegates to main and returns success."""
    manifest = tmp_path / "Cargo.toml"
    manifest.write_text("[workspace]\nmembers = []\n", encoding="utf-8")
    script = Path(threshold.__file__)
    monkeypatch.setattr(sys, "argv", [str(script), str(manifest)])

    with pytest.raises(SystemExit, match="0"):
        runpy.run_path(str(script), run_name="__main__")
