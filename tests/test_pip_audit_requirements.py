"""Tests for hashed-lock pip-audit selection.

The reality-shaped case is the live #961 failure: pip-audit invoked pip on
``requirements-strix-ci-hashes.txt`` containing both ``strix-agent==1.5.3``
and ``cryptography==50.0.0``, pip raised ``ResolutionImpossible``, and the
workflow reported that as a known vulnerability. The helper must audit that
lock with ``--disable-pip`` instead of asking pip to re-resolve metadata.
"""

from __future__ import annotations

import importlib.util
import pathlib
import runpy
import sys
from typing import Any


MODULE_PATH = (
    pathlib.Path(__file__).resolve().parents[1]
    / "scripts"
    / "ci"
    / "pip_audit_requirements.py"
)
WORKFLOW = (
    pathlib.Path(__file__).resolve().parents[1]
    / ".github"
    / "workflows"
    / "python-security.yml"
)
STRIX_WORKFLOW = (
    pathlib.Path(__file__).resolve().parents[1]
    / ".github"
    / "workflows"
    / "strix.yml"
)


def load_module() -> Any:
    """Load the helper from its script path."""

    spec = importlib.util.spec_from_file_location("pip_audit_requirements", MODULE_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _conflicting_strix_lock(path: pathlib.Path) -> None:
    """Write the buyer-shaped hashed lock that pip cannot re-resolve."""

    digest = "a" * 64
    path.write_text(
        "strix-agent==1.5.3 \\\n"
        f"    --hash=sha256:{digest}\n"
        "cryptography==50.0.0 \\\n"
        f"    --hash=sha256:{digest}\n",
        encoding="utf-8",
    )


def test_conflicting_hashed_strix_lock_uses_disable_pip(tmp_path: pathlib.Path) -> None:
    """A 1.5.3 + cryptography 50 lock must not be handed to pip's resolver."""

    module = load_module()
    lock = tmp_path / "requirements-strix-ci-hashes.txt"
    _conflicting_strix_lock(lock)

    command = module.audit_command(lock)

    assert command is not None
    assert command[:5] == [
        "pip-audit",
        "--strict",
        "--desc=on",
        "--disable-pip",
        "-r",
    ]
    assert command[-1] == str(lock)
    assert "--disable-pip" in command


def test_override_file_and_unhashed_input_with_lock_are_skipped(
    tmp_path: pathlib.Path,
) -> None:
    """Compile inputs are not install sets once a hashed sibling exists."""

    module = load_module()
    source = tmp_path / "requirements-strix-ci.txt"
    source.write_text("strix-agent==1.5.3\ncryptography==50.0.0\n", encoding="utf-8")
    lock = tmp_path / "requirements-strix-ci-hashes.txt"
    _conflicting_strix_lock(lock)
    override = tmp_path / "requirements-strix-ci-overrides.txt"
    override.write_text("cryptography==50.0.0\n", encoding="utf-8")

    assert module.audit_command(source) is None
    assert module.audit_command(override) is None
    assert module.hashed_sibling(source) == lock
    assert module.hashed_sibling(lock) is None
    assert module.hashed_sibling(override) is None
    assert module.is_override_file(override) is True


def test_unhashed_requirements_without_lock_keep_resolver_audit(
    tmp_path: pathlib.Path,
) -> None:
    """A standalone unpinned file still uses pip-audit's default resolution."""

    module = load_module()
    requirements = tmp_path / "requirements-demo.txt"
    requirements.write_text("demo==1.0.0\n", encoding="utf-8")
    named_lock = tmp_path / "requirements-strix-ci-hashes.txt"
    named_lock.write_text("strix-agent==1.5.3\n", encoding="utf-8")

    command = module.audit_command(requirements)

    assert command == [
        "pip-audit",
        "--strict",
        "--desc=on",
        "-r",
        str(requirements),
    ]
    assert module.is_hashed_lock(named_lock) is False
    assert "--disable-pip" not in (module.audit_command(named_lock) or [])


def test_discover_skips_git_and_audits_manifest(
    tmp_path: pathlib.Path, capsys: Any
) -> None:
    """``.git`` copies are ignored; a nearby pyproject.toml is audited."""

    module = load_module()
    (tmp_path / ".git").mkdir()
    git_copy = tmp_path / ".git" / "requirements-hidden.txt"
    git_copy.write_text("hidden==1.0.0\n", encoding="utf-8")
    venv = tmp_path / ".venv" / "lib"
    venv.mkdir(parents=True)
    (venv / "requirements-venv.txt").write_text("venv==1.0.0\n", encoding="utf-8")
    visible = tmp_path / "requirements-visible-hashes.txt"
    _conflicting_strix_lock(visible)
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    calls: list[list[str]] = []

    def fake_runner(command: list[str]) -> int:
        calls.append(list(command))
        return 0

    rc = module.run_audits(tmp_path, runner=fake_runner)

    assert rc == 0
    assert [path.name for path in module.discover_requirement_files(tmp_path)] == [
        "requirements-visible-hashes.txt"
    ]
    assert calls[0][3] == "--disable-pip"
    assert calls[1] == ["pip-audit", "--strict", "--desc=on", "."]
    logged = capsys.readouterr().out
    assert "::group::pip-audit" in logged
    assert module.should_audit_project_manifest(tmp_path) is True


def test_failed_hashed_audit_is_not_relabeled_as_missing_input(
    tmp_path: pathlib.Path, capsys: Any
) -> None:
    """A real advisory hit still fails closed with the existing error phrase."""

    module = load_module()
    lock = tmp_path / "requirements-strix-ci-hashes.txt"
    _conflicting_strix_lock(lock)

    rc = module.run_audits(tmp_path, runner=lambda _command: 1)

    assert rc == 1
    err = capsys.readouterr().err
    assert "known-vulnerable Python dependencies" in err


def test_missing_root_fails_closed(tmp_path: pathlib.Path, capsys: Any) -> None:
    """A non-directory root is rejected before any audit command runs."""

    module = load_module()
    rc = module.main([str(tmp_path / "missing-root")])

    assert rc == 2
    assert "audit root is not a directory" in capsys.readouterr().err


def test_empty_tree_without_manifest_is_clean(tmp_path: pathlib.Path) -> None:
    """No requirement files and no PEP 621 manifest is a successful no-op."""

    module = load_module()
    (tmp_path / "notes").mkdir()
    (tmp_path / "notes" / "readme.txt").write_text("not a lock\n", encoding="utf-8")
    (tmp_path / "requirements-not-a-file.txt").mkdir()
    (tmp_path / "stray.txt").write_text("file next to root\n", encoding="utf-8")

    assert module.should_audit_project_manifest(tmp_path) is False
    assert module.discover_requirement_files(tmp_path) == []
    assert module.run_audits(tmp_path, runner=lambda _command: 1) == 0


def test_run_audits_skips_compile_inputs_and_fails_manifest(
    tmp_path: pathlib.Path, capsys: Any
) -> None:
    """Override/input files are skipped; a failing project audit still fails closed."""

    module = load_module()
    source = tmp_path / "requirements-strix-ci.txt"
    source.write_text("strix-agent==1.5.3\n", encoding="utf-8")
    (tmp_path / "requirements-strix-ci-hashes.txt").write_text(
        "strix-agent==1.5.3 --hash=sha256:" + ("b" * 64) + "\n",
        encoding="utf-8",
    )
    (tmp_path / "requirements-strix-ci-overrides.txt").write_text(
        "cryptography==50.0.0\n",
        encoding="utf-8",
    )
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    (tmp_path / "requirements-strix-ci-hashes-dir").mkdir()
    hashed_dir_sibling = tmp_path / "requirements-plain.txt"
    hashed_dir_sibling.write_text("plain==1.0.0\n", encoding="utf-8")
    (tmp_path / "requirements-plain-hashes.txt").mkdir()

    def fake_runner(command: list[str]) -> int:
        return 1 if command[-1] == "." else 0

    rc = module.run_audits(tmp_path, runner=fake_runner)

    assert rc == 1
    logged = capsys.readouterr().out
    assert "skip" in logged
    assert module.hashed_sibling(hashed_dir_sibling) is None


def test_pylock_manifest_and_require_hashes_directive(
    tmp_path: pathlib.Path,
) -> None:
    """A pylock file is recognized; ``--require-hashes`` without hashes is not."""

    module = load_module()
    nested = tmp_path / "svc"
    nested.mkdir()
    (nested / "pylock.svc.toml").write_text("lock = true\n", encoding="utf-8")
    directed = tmp_path / "requirements-directed.txt"
    directed.write_text("--require-hashes\ndemo==1.0.0\n", encoding="utf-8")
    hashed = tmp_path / "requirements-hashed.txt"
    hashed.write_text(
        "--require-hashes\ndemo==1.0.0 --hash=sha256:" + ("a" * 64) + "\n",
        encoding="utf-8",
    )
    comment_only = tmp_path / "requirements-comments.txt"
    comment_only.write_text("# only a comment\n", encoding="utf-8")
    odd = tmp_path / "requirements-odd"
    odd.write_text("demo==1.0.0\n", encoding="utf-8")

    assert module.should_audit_project_manifest(tmp_path) is True
    assert module.is_hashed_lock(directed) is False
    assert "--disable-pip" not in (module.audit_command(directed) or [])
    assert module.is_hashed_lock(hashed) is True
    assert "--disable-pip" in (module.audit_command(hashed) or [])
    assert module.is_hashed_lock(comment_only) is False
    assert module.hashed_sibling(odd) is None
    mixed = tmp_path / "requirements-mixed.txt"
    mixed.write_text(
        "strix-agent==1.5.3 \\\n"
        "    --hash=sha256:" + ("c" * 64) + "\n"
        "unhashed-demo==1.0.0\n",
        encoding="utf-8",
    )
    assert module.is_hashed_lock(mixed) is False
    assert "--disable-pip" not in (module.audit_command(mixed) or [])


def test_workflow_invokes_helper_and_strix_installs_without_resolving() -> None:
    """The live workflows must not keep the resolver-only install or audit loop."""

    security = WORKFLOW.read_text(encoding="utf-8")
    strix = STRIX_WORKFLOW.read_text(encoding="utf-8")
    assert "scripts/ci/pip_audit_requirements.py" in security
    assert "find . -type f -name 'requirements*.txt'" not in security
    assert "--require-hashes --no-deps -r requirements-strix-ci-hashes.txt" in strix
    assert (
        "python3 -m pip install --disable-pip-version-check --no-cache-dir "
        "--require-hashes -r requirements-strix-ci-hashes.txt"
        not in strix
    )


def test_default_runner_invokes_subprocess(
    tmp_path: pathlib.Path, monkeypatch: Any
) -> None:
    """The production runner is ``subprocess.run`` when no test double is passed."""

    module = load_module()
    lock = tmp_path / "requirements-strix-ci-hashes.txt"
    _conflicting_strix_lock(lock)
    seen: list[list[str]] = []

    class Result:
        returncode = 0

    def fake_run(command: list[str], check: bool = False) -> Result:
        seen.append(list(command))
        assert check is False
        return Result()

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    assert module.run_audits(tmp_path) == 0
    assert seen[0][0] == "pip-audit"
    assert "--disable-pip" in seen[0]


def test_module_main_guard_executes(tmp_path: pathlib.Path, monkeypatch: Any) -> None:
    """Running the file as a script exits through ``main``."""

    monkeypatch.setattr(sys, "argv", ["pip_audit_requirements.py", str(tmp_path)])
    try:
        runpy.run_path(str(MODULE_PATH), run_name="__main__")
    except SystemExit as exc:
        assert exc.code == 0
    else:
        raise AssertionError("expected SystemExit from the module main guard")
