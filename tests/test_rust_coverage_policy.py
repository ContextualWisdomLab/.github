"""Tests for central Rust coverage policy selection."""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

import pytest

from scripts.ci import rust_coverage_policy as policy


def _write_manifest(root: Path, text: str) -> Path:
    """Write a Cargo.toml under ``root`` and return its path."""
    manifest = root / "Cargo.toml"
    manifest.write_text(text, encoding="utf-8")
    return manifest


def test_metadata_uses_repository_threshold(tmp_path: Path) -> None:
    """workspace.metadata.opencode.coverage keeps the llvm-cov threshold path."""
    manifest = _write_manifest(
        tmp_path,
        """
[workspace]
members = ["crates/demo"]
rust-version = "1.97"

[workspace.metadata.opencode.coverage]
minimum_lines = 80
""",
    )
    plan = policy.coverage_plan(repo_root=tmp_path, manifest=manifest)
    assert plan.mode == "llvm-cov-threshold"
    assert plan.fail_under == 80
    assert plan.verifier is None


def test_originweave_style_verifier_skips_default_100(tmp_path: Path) -> None:
    """A rust-version 1.97 workspace with verify_coverage.py is not default 100."""
    manifest = _write_manifest(
        tmp_path,
        """
[workspace]
members = ["crates/demo"]
rust-version = "1.97"
""",
    )
    verifier = tmp_path / "scripts" / "ci" / "verify_coverage.py"
    verifier.parent.mkdir(parents=True)
    verifier.write_text("print('ok')\n", encoding="utf-8")
    plan = policy.coverage_plan(repo_root=tmp_path, manifest=manifest)
    assert plan.mode == "repo-verifier"
    assert plan.fail_under is None
    assert plan.verifier == verifier


def test_shell_verifier_is_accepted(tmp_path: Path) -> None:
    """A non-symlink verify_coverage.sh is a repo verifier."""
    manifest = _write_manifest(tmp_path, "[workspace]\nmembers = []\n")
    verifier = tmp_path / "scripts" / "ci" / "verify_coverage.sh"
    verifier.parent.mkdir(parents=True)
    verifier.write_text("#!/bin/sh\n", encoding="utf-8")
    plan = policy.coverage_plan(repo_root=tmp_path, manifest=manifest)
    assert plan.mode == "repo-verifier"
    assert plan.verifier == verifier


def test_symlink_verifier_is_ignored(tmp_path: Path) -> None:
    """Symlinked verifiers are not trusted coverage evidence."""
    manifest = _write_manifest(tmp_path, "[workspace]\nmembers = []\n")
    target = tmp_path / "outside.py"
    target.write_text("print('leak')\n", encoding="utf-8")
    verifier = tmp_path / "scripts" / "ci" / "verify_coverage.py"
    verifier.parent.mkdir(parents=True)
    verifier.symlink_to(target)
    plan = policy.coverage_plan(repo_root=tmp_path, manifest=manifest)
    assert plan.mode == "llvm-cov-threshold"
    assert plan.fail_under == 100


def test_no_metadata_and_no_verifier_defaults_to_100(tmp_path: Path) -> None:
    """Only a workspace with neither metadata nor a verifier inherits 100."""
    manifest = _write_manifest(
        tmp_path,
        """
[workspace]
members = ["crates/demo"]
rust-version = "1.97"
""",
    )
    plan = policy.coverage_plan(repo_root=tmp_path, manifest=manifest)
    assert plan.mode == "llvm-cov-threshold"
    assert plan.fail_under == 100


def test_empty_coverage_table_still_uses_threshold_path(tmp_path: Path) -> None:
    """An empty opencode.coverage table keeps llvm-cov and defaults to 100."""
    manifest = _write_manifest(
        tmp_path,
        """
[workspace.metadata.opencode.coverage]
""",
    )
    plan = policy.coverage_plan(repo_root=tmp_path, manifest=manifest)
    assert plan.mode == "llvm-cov-threshold"
    assert plan.fail_under == 100


def test_package_metadata_uses_threshold(tmp_path: Path) -> None:
    """package.metadata.opencode.coverage is a repository-owned baseline."""
    manifest = _write_manifest(
        tmp_path,
        """
[package]
name = "demo"
version = "0.1.0"

[package.metadata.opencode.coverage]
minimum_lines = 70
""",
    )
    plan = policy.coverage_plan(repo_root=tmp_path, manifest=manifest)
    assert plan.mode == "llvm-cov-threshold"
    assert plan.fail_under == 70


def test_invalid_minimum_lines_fails_closed(tmp_path: Path) -> None:
    """A non-numeric coverage baseline is not silently defaulted."""
    manifest = _write_manifest(
        tmp_path,
        """
[workspace.metadata.opencode.coverage]
minimum_lines = true
""",
    )
    with pytest.raises(ValueError, match="must be a number"):
        policy.coverage_plan(repo_root=tmp_path, manifest=manifest)


def test_parse_manifest_rejects_non_table(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A non-table TOML root fails closed."""
    manifest = _write_manifest(tmp_path, "[workspace]\n")
    monkeypatch.setattr(policy.tomllib, "loads", lambda _text: [])
    with pytest.raises(ValueError, match="root must be a table"):
        policy.coverage_plan(repo_root=tmp_path, manifest=manifest)


def test_invalid_toml_raises(tmp_path: Path) -> None:
    """Malformed Cargo.toml fails closed."""
    manifest = _write_manifest(tmp_path, "[workspace\n")
    with pytest.raises(ValueError, match="invalid Cargo.toml"):
        policy.coverage_plan(repo_root=tmp_path, manifest=manifest)


def test_metadata_lookup_ignores_non_tables() -> None:
    """Non-table workspace/metadata/opencode/coverage values are not metadata."""
    assert policy._opencode_coverage_metadata({}) is None
    assert policy._opencode_coverage_metadata({"workspace": []}) is None
    assert policy._opencode_coverage_metadata({"package": []}) is None
    assert policy._opencode_coverage_metadata({"package": {"metadata": []}}) is None
    assert policy._opencode_coverage_metadata(
        {"package": {"metadata": {"opencode": []}}}
    ) is None
    assert policy._opencode_coverage_metadata({"workspace": {}}) is None
    assert policy._opencode_coverage_metadata({"workspace": {"metadata": []}}) is None
    assert policy._opencode_coverage_metadata(
        {"workspace": {"metadata": {"opencode": []}}}
    ) is None
    assert policy._opencode_coverage_metadata(
        {"workspace": {"metadata": {"opencode": {}}}}
    ) is None
    assert policy._opencode_coverage_metadata(
        {"workspace": {"metadata": {"opencode": {"coverage": []}}}}
    ) is None
    assert policy._opencode_coverage_metadata(
        {"package": {"metadata": {"opencode": {"coverage": {"minimum_lines": 70}}}}}
    ) == {"minimum_lines": 70}


def test_rustc_cargo_version_log_includes_optional_rustup() -> None:
    """Toolchain identity is formatted for coverage_summary."""
    assert policy.rustc_cargo_version_log(rustc="", cargo="") == (
        "rustc: unavailable\ncargo: unavailable\n"
    )
    logged = policy.rustc_cargo_version_log(
        rustc="rustc 1.97.1",
        cargo="cargo 1.97.1",
        rustup_show="1.97.1-x86_64-unknown-linux-gnu",
    )
    assert "rustc: rustc 1.97.1" in logged
    assert "cargo: cargo 1.97.1" in logged
    assert "rustup show: 1.97.1-x86_64-unknown-linux-gnu" in logged


def test_plan_fields_and_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """The workflow CLI emits tab-separated mode, threshold, and verifier."""
    manifest = _write_manifest(tmp_path, "[workspace]\nmembers = []\n")
    assert (
        policy.main(
            ["--repo-root", str(tmp_path), "--manifest", str(manifest)]
        )
        == 0
    )
    assert capsys.readouterr().out == "llvm-cov-threshold\t100\t\n"
    assert policy.main(["--repo-root", str(tmp_path), "--manifest", str(tmp_path / "missing.toml")]) == 2
    assert "invalid Rust coverage policy" in capsys.readouterr().err


def test_script_entrypoint(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The executable coverage-policy entrypoint delegates to main."""
    manifest = _write_manifest(tmp_path, "[workspace]\nmembers = []\n")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "rust_coverage_policy.py",
            "--repo-root",
            str(tmp_path),
            "--manifest",
            str(manifest),
        ],
    )
    with pytest.raises(SystemExit, match="0"):
        runpy.run_path(str(Path(policy.__file__)), run_name="__main__")
