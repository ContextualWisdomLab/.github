"""Fail-closed regressions for Python requirement audit discovery.

These tests protect the pull-request security boundary: a repository-controlled
filename, sibling file, encoding error, or pip option must not suppress the
install set that ``pip-audit`` evaluates or forge GitHub Actions log commands.
"""

from __future__ import annotations

import importlib.util
import pathlib
from typing import Any

import pytest


MODULE_PATH = (
    pathlib.Path(__file__).resolve().parents[1]
    / "scripts"
    / "ci"
    / "pip_audit_requirements.py"
)


def load_module() -> Any:
    """Load the production helper from its script path."""

    spec = importlib.util.spec_from_file_location(
        "pip_audit_requirements_fail_closed", MODULE_PATH
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_valid_lock(path: pathlib.Path) -> None:
    """Write one exact package pin with a complete SHA-256 hash."""

    path.write_text(
        "demo==1.0.0 --hash=sha256:" + ("a" * 64) + "\n",
        encoding="utf-8",
    )


def test_invalid_hash_sibling_cannot_suppress_source_audit(
    tmp_path: pathlib.Path,
) -> None:
    """An empty or directive-only sibling is not an audited install set."""

    module = load_module()
    source = tmp_path / "requirements-demo.txt"
    source.write_text("demo==1.0.0\n", encoding="utf-8")
    sibling = tmp_path / "requirements-demo-hashes.txt"
    sibling.write_text("--require-hashes\n", encoding="utf-8")

    assert module.hashed_sibling(source) is None
    assert module.audit_command(source) == [
        "pip-audit",
        "--strict",
        "--desc=on",
        "-r",
        str(source),
    ]


def test_pip_option_with_hash_is_not_a_complete_lock(tmp_path: pathlib.Path) -> None:
    """A hash-shaped pip option cannot earn ``--disable-pip`` treatment."""

    module = load_module()
    requirements = tmp_path / "requirements-option.txt"
    requirements.write_text(
        "--index-url https://example.invalid/simple --hash=sha256:"
        + ("b" * 64)
        + "\n",
        encoding="utf-8",
    )

    assert module.is_hashed_lock(requirements) is False
    assert "--disable-pip" not in (module.audit_command(requirements) or [])


def test_invalid_utf8_fails_before_any_audit_command(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Undecodable requirement bytes cannot disappear from the audited set."""

    module = load_module()
    requirements = tmp_path / "requirements-invalid.txt"
    requirements.write_bytes(b"demo==1.0.0\xff\n")
    calls: list[list[str]] = []

    result = module.run_audits(
        tmp_path,
        runner=lambda command: calls.append(list(command)) or 0,
    )

    assert result == 2
    assert calls == []
    error = capsys.readouterr().err
    assert "invalid UTF-8 requirements input" in error
    assert "0xff" not in error


def test_requirement_symlink_is_rejected_instead_of_followed(
    tmp_path: pathlib.Path,
) -> None:
    """A tracked-looking symlink cannot redirect audit input outside the tree."""

    module = load_module()
    outside = tmp_path / "outside.txt"
    _write_valid_lock(outside)
    link = tmp_path / "requirements-link.txt"
    link.symlink_to(outside)
    error_type = getattr(module, "AuditConfigurationError", RuntimeError)

    with pytest.raises(error_type, match="regular non-symlink file"):
        module.discover_requirement_files(tmp_path)


def test_symlink_hash_sibling_cannot_suppress_source_audit(
    tmp_path: pathlib.Path,
) -> None:
    """A symlink ``*-hashes.txt`` sibling is not a regular complete lock."""

    module = load_module()
    source = tmp_path / "requirements-demo.txt"
    source.write_text("demo==1.0.0\n", encoding="utf-8")
    outside = tmp_path / "outside-lock.txt"
    _write_valid_lock(outside)
    sibling = tmp_path / "requirements-demo-hashes.txt"
    sibling.symlink_to(outside)

    assert module.hashed_sibling(source) is None
    assert module.audit_command(source) == [
        "pip-audit",
        "--strict",
        "--desc=on",
        "-r",
        str(source),
    ]
    assert "--disable-pip" not in (module.audit_command(source) or [])


def test_filename_only_requirement_is_not_a_complete_lock(
    tmp_path: pathlib.Path,
) -> None:
    """A hashed wheel path without an exact ``==`` pin cannot bypass pip."""

    module = load_module()
    requirements = tmp_path / "requirements-wheel.txt"
    requirements.write_text(
        "./demo-1.0.0-py3-none-any.whl --hash=sha256:" + ("c" * 64) + "\n",
        encoding="utf-8",
    )

    assert module.is_hashed_lock(requirements) is False
    assert "--disable-pip" not in (module.audit_command(requirements) or [])


def test_valid_regular_hash_sibling_still_suppresses_compile_input(
    tmp_path: pathlib.Path,
) -> None:
    """The fail-closed checks preserve the intended complete-lock fast path."""

    module = load_module()
    source = tmp_path / "requirements-demo.txt"
    source.write_text("demo==1.0.0\n", encoding="utf-8")
    sibling = tmp_path / "requirements-demo-hashes.txt"
    _write_valid_lock(sibling)

    assert module.hashed_sibling(source) == sibling
    assert module.audit_command(source) is None
    assert "--disable-pip" in (module.audit_command(sibling) or [])


def test_control_characters_in_paths_are_escaped_in_workflow_logs(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A filename newline cannot inject a GitHub Actions workflow command."""

    module = load_module()
    hostile = tmp_path / "requirements-bad\n::error::forged.txt"
    _write_valid_lock(hostile)

    assert module.run_audits(tmp_path, runner=lambda _command: 0) == 0
    output = capsys.readouterr().out
    assert "\\n::error::forged.txt" in output
    assert "\n::error::forged.txt" not in output
