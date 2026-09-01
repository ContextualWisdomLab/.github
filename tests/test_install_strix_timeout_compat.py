"""Tests for installing the trusted Strix compatibility executable."""

from __future__ import annotations

from pathlib import Path
import stat

import pytest

from scripts.ci import install_strix_timeout_compat as installer


def trusted_environment(tmp_path: Path) -> tuple[dict[str, str], Path, Path]:
    """Create valid executable, scripts-root, and GitHub environment evidence."""
    scripts_root = tmp_path / "bin"
    scripts_root.mkdir(mode=0o755)
    executable = scripts_root / "strix"
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(0o755)
    github_env = tmp_path / "github-env"
    github_env.write_text("", encoding="utf-8")
    environ = {
        "GITHUB_ACTIONS": "true",
        "GITHUB_ENV": str(github_env),
        "STRIX_EXECUTABLE_PATH": str(executable),
        "STRIX_EXECUTABLE_ROOT": str(scripts_root),
        "STRIX_EXECUTABLE_SHA256": installer.sha256_file(executable),
    }
    return environ, executable, github_env


def test_installer_is_noop_outside_strix_github_actions(tmp_path: Path) -> None:
    """Other contextual-orchestrator consumers never receive a Strix wrapper."""
    assert installer.install_compatibility_launcher(environ={}) is None
    assert (
        installer.install_compatibility_launcher(
            environ={"GITHUB_ACTIONS": "true"},
        )
        is None
    )


def test_installer_atomically_publishes_pinned_wrapper(tmp_path: Path) -> None:
    """A valid pinned executable is replaced in later steps by a read-only wrapper."""
    environ, _, github_env = trusted_environment(tmp_path)
    source = tmp_path / "launcher.py"
    source.write_text("#!/usr/bin/env python3\nprint('compat')\n", encoding="utf-8")

    target = installer.install_compatibility_launcher(
        environ=environ,
        source_path=source,
    )

    assert target == tmp_path / "bin/strix-contextual-orchestrator"
    assert target.read_bytes() == source.read_bytes()
    assert target.stat().st_mode & (stat.S_IWGRP | stat.S_IWOTH) == 0
    exported = github_env.read_text(encoding="utf-8")
    assert f"STRIX_EXECUTABLE_PATH={target}\n" in exported
    assert f"STRIX_EXECUTABLE_SHA256={installer.sha256_file(target)}\n" in exported
    assert not list((tmp_path / "bin").glob(".strix-contextual-orchestrator.*"))


def test_installer_requires_complete_environment(tmp_path: Path) -> None:
    """Partially configured Strix evidence fails with the missing field name."""
    with pytest.raises(installer.CompatibilityInstallError, match="STRIX_EXECUTABLE_ROOT"):
        installer.install_compatibility_launcher(
            environ={
                "GITHUB_ACTIONS": "true",
                "STRIX_EXECUTABLE_PATH": str(tmp_path / "strix"),
            }
        )


def test_installer_rejects_symlinked_inputs(tmp_path: Path) -> None:
    """A symlink cannot redirect the trusted wrapper or environment output."""
    environ, executable, _ = trusted_environment(tmp_path)
    symlink = tmp_path / "strix-link"
    symlink.symlink_to(executable)
    environ["STRIX_EXECUTABLE_PATH"] = str(symlink)
    environ["STRIX_EXECUTABLE_SHA256"] = installer.sha256_file(executable)

    with pytest.raises(installer.CompatibilityInstallError, match="must not be symlinks"):
        installer.install_compatibility_launcher(environ=environ)


def test_installer_rejects_path_outside_scripts_root(tmp_path: Path) -> None:
    """The trusted executable must remain inside the installation root."""
    environ, _, _ = trusted_environment(tmp_path)
    outside = tmp_path / "outside"
    outside.write_text("#!/bin/sh\n", encoding="utf-8")
    outside.chmod(0o755)
    environ["STRIX_EXECUTABLE_PATH"] = str(outside)
    environ["STRIX_EXECUTABLE_SHA256"] = installer.sha256_file(outside)

    with pytest.raises(installer.CompatibilityInstallError, match="inside the pinned"):
        installer.install_compatibility_launcher(environ=environ)


def test_installer_rejects_nonregular_and_nonexecutable_evidence(tmp_path: Path) -> None:
    """Invalid root, source, executable, or environment evidence fails closed."""
    environ, executable, github_env = trusted_environment(tmp_path)
    root_file = tmp_path / "root-file"
    root_file.write_text("#!/bin/sh\n", encoding="utf-8")
    root_file.chmod(0o755)
    invalid_root_environment = dict(environ)
    invalid_root_environment["STRIX_EXECUTABLE_ROOT"] = str(root_file)
    invalid_root_environment["STRIX_EXECUTABLE_PATH"] = str(root_file)
    invalid_root_environment["STRIX_EXECUTABLE_SHA256"] = installer.sha256_file(root_file)
    with pytest.raises(installer.CompatibilityInstallError, match="not regular"):
        installer.install_compatibility_launcher(environ=invalid_root_environment)

    executable.chmod(0o644)
    with pytest.raises(installer.CompatibilityInstallError, match="not executable"):
        installer.install_compatibility_launcher(environ=environ)
    executable.chmod(0o755)

    missing_source = tmp_path / "missing.py"
    with pytest.raises(installer.CompatibilityInstallError, match="must resolve"):
        installer.install_compatibility_launcher(
            environ=environ,
            source_path=missing_source,
        )

    github_env.unlink()
    github_env.mkdir()
    with pytest.raises(installer.CompatibilityInstallError, match="must be regular"):
        installer.install_compatibility_launcher(environ=environ)


def test_installer_rejects_writable_root_and_invalid_digest(tmp_path: Path) -> None:
    """Mutable installation roots and malformed or stale digests are rejected."""
    environ, executable, _ = trusted_environment(tmp_path)
    scripts_root = Path(environ["STRIX_EXECUTABLE_ROOT"])
    scripts_root.chmod(0o775)
    with pytest.raises(installer.CompatibilityInstallError, match="group/world writable"):
        installer.install_compatibility_launcher(environ=environ)
    scripts_root.chmod(0o755)

    environ["STRIX_EXECUTABLE_SHA256"] = "bad"
    with pytest.raises(installer.CompatibilityInstallError, match="malformed"):
        installer.install_compatibility_launcher(environ=environ)

    environ["STRIX_EXECUTABLE_SHA256"] = "0" * 64
    with pytest.raises(installer.CompatibilityInstallError, match="digest changed"):
        installer.install_compatibility_launcher(environ=environ)

    executable.write_text("changed", encoding="utf-8")
    environ["STRIX_EXECUTABLE_SHA256"] = installer.sha256_file(executable)
    assert len(environ["STRIX_EXECUTABLE_SHA256"]) == 64


def test_main_uses_environment_installer() -> None:
    """The executable entry point delegates once to the environment installer."""
    called: list[str] = []
    installer.main(lambda: called.append("installed"))
    assert called == ["installed"]


def test_main_formats_install_failure(capsys: pytest.CaptureFixture[str]) -> None:
    """Installer failures become concise GitHub Actions errors without a traceback."""

    def fail() -> None:
        raise installer.CompatibilityInstallError("broken evidence")

    with pytest.raises(SystemExit, match="1"):
        installer.main(fail)
    assert capsys.readouterr().err == "::error::broken evidence\n"
