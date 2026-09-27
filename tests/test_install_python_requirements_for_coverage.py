"""Tests for coverage dependency-install policy logging."""

from __future__ import annotations

import importlib.util
import pathlib
import runpy
import sys


MODULE_PATH = (
    pathlib.Path(__file__).resolve().parents[1]
    / "scripts"
    / "ci"
    / "install_python_requirements_for_coverage.py"
)


def load_module():
    """Load the helper from its script path."""
    spec = importlib.util.spec_from_file_location(
        "install_python_requirements_for_coverage", MODULE_PATH
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_missing_requirements_file_fails_with_visible_reason(tmp_path, capsys):
    """Missing input fails closed before any installer is invoked."""
    module = load_module()

    rc = module.main([str(tmp_path / "missing.txt")])

    assert rc == 2
    assert "requirements file not found" in capsys.readouterr().err


def test_blank_and_comment_only_requirements_are_hash_safe(tmp_path):
    """Empty requirements files do not need network dependency resolution."""
    module = load_module()
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("\n# comment only\n", encoding="utf-8")

    assert module._requirement_lines(requirements) == []
    assert module._has_hash_pins(requirements) is True


def test_hash_pinned_requirements_use_pip_require_hashes(tmp_path, monkeypatch):
    """Hash-pinned target requirements install with pip hash verification."""
    module = load_module()
    requirements = tmp_path / "requirements.txt"
    requirements.write_text(
        "demo==1.0 --hash=sha256:" + ("a" * 64) + "\n",
        encoding="utf-8",
    )
    calls: list[tuple[list[str], pathlib.Path]] = []

    def fake_run(command, cwd):
        calls.append((command, cwd))
        return 0

    monkeypatch.setattr(module, "_run", fake_run)

    rc = module.main([str(requirements)])

    assert rc == 0
    command, cwd = calls[0]
    assert command[:5] == [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
    ]
    assert "--require-hashes" in command
    assert cwd == tmp_path


def test_unhashed_requirements_use_uv_with_warning(tmp_path, monkeypatch, capsys):
    """Unhashed target requirements are visibly marked coverage-only."""
    module = load_module()
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("demo==1.0\n", encoding="utf-8")
    calls: list[tuple[list[str], pathlib.Path]] = []

    monkeypatch.setattr(module.shutil, "which", lambda name: "/usr/bin/uv")

    def fake_run(command, cwd):
        calls.append((command, cwd))
        return 0

    monkeypatch.setattr(module, "_run", fake_run)

    rc = module.main([str(requirements)])

    assert rc == 0
    assert calls == [
        (
            ["/usr/bin/uv", "pip", "install", "--system", "-r", str(requirements)],
            tmp_path,
        )
    ]
    assert "not hash-pinned" in capsys.readouterr().out


def test_unhashed_requirements_fail_when_uv_is_unavailable(tmp_path, monkeypatch, capsys):
    """Unhashed target requirements fail closed when uv cannot sandbox install."""
    module = load_module()
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("demo==1.0\n", encoding="utf-8")
    monkeypatch.setattr(module.shutil, "which", lambda name: None)

    rc = module.main([str(requirements)])

    assert rc == 1
    assert "uv is unavailable" in capsys.readouterr().err


def test_run_returns_subprocess_status(tmp_path):
    """Command execution returns the subprocess exit code."""
    module = load_module()

    rc = module._run([sys.executable, "-c", "raise SystemExit(7)"], tmp_path)

    assert rc == 7


def test_script_entrypoint_exits_through_main(tmp_path, monkeypatch):
    """The script entry point delegates to main and exits with its return code."""
    missing = tmp_path / "missing.txt"
    monkeypatch.setattr(sys, "argv", [str(MODULE_PATH), str(missing)])

    try:
        runpy.run_path(str(MODULE_PATH), run_name="__main__")
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("expected SystemExit")
