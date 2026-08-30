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


def test_nested_independent_workspace_does_not_inherit_outer_baseline(
    tmp_path: Path,
) -> None:
    """A nested [workspace] boundary with no baseline must not leak an outer one.

    Regression for Devin finding "Independent crates inherit unrelated
    thresholds": the walk must stop at the nearest ancestor workspace even
    when that workspace configures no coverage metadata of its own, rather
    than continuing past it to an unrelated, further-out workspace.
    """
    outer_workspace = tmp_path / "Cargo.toml"
    outer_workspace.write_text(
        '[workspace]\nmembers = ["libs/*"]\n\n'
        "[workspace.metadata.opencode.coverage]\nminimum_lines = 70\n",
        encoding="utf-8",
    )
    inner_workspace = tmp_path / "libs" / "independent" / "Cargo.toml"
    inner_workspace.parent.mkdir(parents=True)
    inner_workspace.write_text('[workspace]\nmembers = ["crate_a"]\n', encoding="utf-8")
    manifest = tmp_path / "libs" / "independent" / "crate_a" / "Cargo.toml"
    manifest.parent.mkdir(parents=True)
    manifest.write_text('[package]\nname = "crate_a"\nversion = "0.1.0"\n', encoding="utf-8")

    assert threshold.read_minimum_lines(manifest) is None


def test_nested_independent_workspace_own_baseline_wins(tmp_path: Path) -> None:
    """A nested workspace's own baseline is used, never the outer workspace's."""
    outer_workspace = tmp_path / "Cargo.toml"
    outer_workspace.write_text(
        '[workspace]\nmembers = ["libs/*"]\n\n'
        "[workspace.metadata.opencode.coverage]\nminimum_lines = 70\n",
        encoding="utf-8",
    )
    inner_workspace = tmp_path / "libs" / "independent" / "Cargo.toml"
    inner_workspace.parent.mkdir(parents=True)
    inner_workspace.write_text(
        '[workspace]\nmembers = ["crate_a"]\n\n'
        "[workspace.metadata.opencode.coverage]\nminimum_lines = 95\n",
        encoding="utf-8",
    )
    manifest = tmp_path / "libs" / "independent" / "crate_a" / "Cargo.toml"
    manifest.parent.mkdir(parents=True)
    manifest.write_text('[package]\nname = "crate_a"\nversion = "0.1.0"\n', encoding="utf-8")

    assert threshold.read_minimum_lines(manifest) == 95.0


def test_excluded_package_does_not_inherit_outer_workspace_baseline(
    tmp_path: Path,
) -> None:
    """A package excluded from an outer workspace must not inherit its baseline.

    Regression for Devin finding "Independent crates inherit unrelated
    thresholds": ``exclude`` removes the package from that workspace, so its
    metadata must not apply -- even though the excluded package still lives
    in a directory beneath the workspace root.
    """
    workspace = tmp_path / "Cargo.toml"
    workspace.write_text(
        '[workspace]\nmembers = ["crates/*"]\nexclude = ["crates/excluded"]\n\n'
        "[workspace.metadata.opencode.coverage]\nminimum_lines = 70\n",
        encoding="utf-8",
    )
    manifest = tmp_path / "crates" / "excluded" / "Cargo.toml"
    manifest.parent.mkdir(parents=True)
    manifest.write_text('[package]\nname = "excluded"\nversion = "0.1.0"\n', encoding="utf-8")

    assert threshold.read_minimum_lines(manifest) is None


def test_excluded_package_still_inherits_further_ancestor_workspace(
    tmp_path: Path,
) -> None:
    """A package excluded from one workspace may still inherit a further one.

    Mirrors Cargo's own root-discovery rule: an ancestor workspace that
    excludes the package is not its root, so the search must continue
    upward rather than stopping at the excluding workspace.
    """
    grandparent_workspace = tmp_path / "Cargo.toml"
    grandparent_workspace.write_text(
        '[workspace]\nmembers = ["nested/crates/*"]\n\n'
        "[workspace.metadata.opencode.coverage]\nminimum_lines = 60\n",
        encoding="utf-8",
    )
    nested_workspace = tmp_path / "nested" / "Cargo.toml"
    nested_workspace.parent.mkdir(parents=True)
    nested_workspace.write_text(
        '[workspace]\nmembers = ["crates/*"]\nexclude = ["crates/excluded"]\n',
        encoding="utf-8",
    )
    manifest = tmp_path / "nested" / "crates" / "excluded" / "Cargo.toml"
    manifest.parent.mkdir(parents=True)
    manifest.write_text('[package]\nname = "excluded"\nversion = "0.1.0"\n', encoding="utf-8")

    assert threshold.read_minimum_lines(manifest) == 60.0


def test_relative_posix_path_returns_none_for_unrelated_paths(tmp_path: Path) -> None:
    """An unrelated path pair cannot be expressed as a relative path."""
    workspace_dir = tmp_path / "workspace"
    other_dir = tmp_path / "elsewhere" / "package"
    workspace_dir.mkdir()
    other_dir.mkdir(parents=True)

    assert threshold._relative_posix_path(other_dir, workspace_dir) is None


def test_workspace_excludes_package_ignores_non_dict_workspace_table() -> None:
    """A malformed non-table [workspace] value never signals exclusion."""
    assert (
        threshold._workspace_excludes_package(
            Path("/repo"), Path("/repo/crates/a"), {"workspace": "not-a-table"}
        )
        is False
    )


def test_workspace_excludes_package_ignores_non_list_exclude() -> None:
    """A malformed non-list exclude value never signals exclusion."""
    assert (
        threshold._workspace_excludes_package(
            Path("/repo"),
            Path("/repo/crates/a"),
            {"workspace": {"exclude": "crates/a"}},
        )
        is False
    )


def test_workspace_excludes_package_ignores_unrelated_package_directory(
    tmp_path: Path,
) -> None:
    """A package outside the workspace directory can never be excluded by it."""
    workspace_dir = tmp_path / "workspace"
    other_dir = tmp_path / "elsewhere" / "package"

    assert (
        threshold._workspace_excludes_package(
            workspace_dir, other_dir, {"workspace": {"exclude": ["package"]}}
        )
        is False
    )


def test_workspace_excludes_package_skips_non_string_patterns_and_checks_rest() -> None:
    """A non-string exclude entry is skipped rather than raising or matching."""
    assert (
        threshold._workspace_excludes_package(
            Path("/repo"),
            Path("/repo/crates/a"),
            {"workspace": {"exclude": [42, "crates/a"]}},
        )
        is True
    )
    assert (
        threshold._workspace_excludes_package(
            Path("/repo"),
            Path("/repo/crates/other"),
            {"workspace": {"exclude": [42, "crates/a"]}},
        )
        is False
    )


def test_excluded_package_directory_beneath_excluded_subtree(tmp_path: Path) -> None:
    """A package nested beneath an excluded directory inherits its exclusion.

    Covers the exclude-prefix branch: the package path is not an exact or
    glob match for the exclude entry, only a path beneath it.
    """
    workspace = tmp_path / "Cargo.toml"
    workspace.write_text(
        '[workspace]\nmembers = ["tools/legacy/*"]\nexclude = ["tools/legacy"]\n\n'
        "[workspace.metadata.opencode.coverage]\nminimum_lines = 70\n",
        encoding="utf-8",
    )
    manifest = tmp_path / "tools" / "legacy" / "sub" / "Cargo.toml"
    manifest.parent.mkdir(parents=True)
    manifest.write_text('[package]\nname = "sub"\nversion = "0.1.0"\n', encoding="utf-8")

    assert threshold.read_minimum_lines(manifest) is None


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
