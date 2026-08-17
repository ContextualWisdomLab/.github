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


def test_directory_symlink_cannot_import_outside_requirements(
    tmp_path: pathlib.Path,
) -> None:
    """A directory symlink cannot pull an outside lock into the audit set."""

    module = load_module()
    outside = tmp_path / "outside-tree"
    outside.mkdir()
    secret = outside / "requirements-secret.txt"
    _write_valid_lock(secret)
    root = tmp_path / "repo"
    root.mkdir()
    (root / "vendor").symlink_to(outside)
    presented = root / "vendor" / "requirements-secret.txt"
    calls: list[list[str]] = []

    result = module.run_audits(
        root,
        runner=lambda command: calls.append(list(command)) or 0,
    )

    assert result == 0
    assert calls == []
    assert module.discover_requirement_files(root) == []
    with pytest.raises(module.AuditConfigurationError, match="escaped the audit root"):
        module._reject_escaped_requirement_path(root, presented)


def test_parent_symlink_inside_root_is_still_rejected(
    tmp_path: pathlib.Path,
) -> None:
    """An intermediate directory symlink is fail-closed even when it stays inside."""

    module = load_module()
    nested = tmp_path / "nested"
    nested.mkdir()
    real = nested / "requirements-in.txt"
    _write_valid_lock(real)
    (tmp_path / "alias").symlink_to(nested)
    presented = tmp_path / "alias" / "requirements-in.txt"

    found = module.discover_requirement_files(tmp_path)
    assert found == [real]
    with pytest.raises(module.AuditConfigurationError, match="escaped the audit root"):
        module._reject_escaped_requirement_path(tmp_path, presented)
    deeper = tmp_path / "pkg" / "nested"
    deeper.mkdir(parents=True)
    deep_lock = deeper / "requirements-lib.txt"
    _write_valid_lock(deep_lock)
    assert deep_lock in module.discover_requirement_files(tmp_path)


def test_index_url_config_does_not_block_a_complete_hashed_lock(
    tmp_path: pathlib.Path,
) -> None:
    """A resolver config option is not a package line and cannot hide a real lock."""

    module = load_module()
    digest = "d" * 64
    lock = tmp_path / "requirements-index.txt"
    lock.write_text(
        "--index-url https://pypi.org/simple\n"
        f"demo==1.0.0 --hash=sha256:{digest}\n",
        encoding="utf-8",
    )
    equals_form = tmp_path / "requirements-index-eq.txt"
    equals_form.write_text(
        f"--extra-index-url=https://example.invalid/simple\ndemo==1.0.0 --hash=sha256:{digest}\n",
        encoding="utf-8",
    )
    include = tmp_path / "requirements-include.txt"
    include.write_text(
        f"-r more.txt\ndemo==1.0.0 --hash=sha256:{digest}\n",
        encoding="utf-8",
    )

    assert module.is_hashed_lock(lock) is True
    assert "--disable-pip" in (module.audit_command(lock) or [])
    assert module.is_hashed_lock(equals_form) is True
    assert module.is_hashed_lock(include) is False
    assert "--disable-pip" not in (module.audit_command(include) or [])


def test_unstatable_parent_and_unresolvable_hit_fail_closed(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A parent that cannot be inspected or resolved cannot enter the audit set."""

    module = load_module()
    nested = tmp_path / "nested"
    nested.mkdir()
    lock = nested / "requirements-ci.txt"
    _write_valid_lock(lock)
    original_is_symlink = pathlib.Path.is_symlink
    original_resolve = pathlib.Path.resolve

    def flaky_symlink(self: pathlib.Path) -> bool:
        if self.name == "nested":
            raise OSError("parent gone")
        return original_is_symlink(self)

    monkeypatch.setattr(pathlib.Path, "is_symlink", flaky_symlink)
    with pytest.raises(module.AuditConfigurationError, match="could not be inspected"):
        module.discover_requirement_files(tmp_path)

    monkeypatch.setattr(pathlib.Path, "is_symlink", original_is_symlink)

    def boom_resolve(self: pathlib.Path, strict: bool = False) -> pathlib.Path:
        if self.name == "requirements-ci.txt":
            raise OSError("vanished")
        return original_resolve(self, strict=strict)

    monkeypatch.setattr(pathlib.Path, "resolve", boom_resolve)
    with pytest.raises(module.AuditConfigurationError, match="could not be inspected"):
        module.discover_requirement_files(tmp_path)

    def escape_resolve(self: pathlib.Path, strict: bool = False) -> pathlib.Path:
        if self.name == "requirements-ci.txt":
            return pathlib.Path("/tmp/outside-requirements.txt")
        return original_resolve(self, strict=strict)

    monkeypatch.setattr(pathlib.Path, "resolve", escape_resolve)
    with pytest.raises(module.AuditConfigurationError, match="escaped the audit root"):
        module.discover_requirement_files(tmp_path)

    monkeypatch.setattr(pathlib.Path, "resolve", original_resolve)
    original_relative_to = pathlib.Path.relative_to

    def parent_leaves(self: pathlib.Path, other: pathlib.Path) -> pathlib.PurePath:
        if self.name == "nested":
            raise ValueError("left")
        return original_relative_to(self, other)

    monkeypatch.setattr(pathlib.Path, "relative_to", parent_leaves)
    with pytest.raises(module.AuditConfigurationError, match="escaped the audit root"):
        module.discover_requirement_files(tmp_path)
