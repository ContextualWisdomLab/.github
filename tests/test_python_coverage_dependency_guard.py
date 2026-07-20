"""Tests for base-declared networkless coverage dependency classification."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import runpy
import subprocess
import sys

import pytest


MODULE_PATH = (
    Path(__file__).parents[1] / "scripts" / "ci" / "python_coverage_dependency_guard.py"
)


def load_module():
    spec = importlib.util.spec_from_file_location(
        "python_coverage_dependency_guard", MODULE_PATH
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    ).stdout.strip()


def make_repo(
    tmp_path: Path, manifest: str, *, pyproject: bool = False
) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    (repo / "backend").mkdir(parents=True)
    filename = "pyproject.toml" if pyproject else "requirements.txt"
    (repo / "backend" / filename).write_text(manifest, encoding="utf-8")
    git(repo, "init", "--quiet")
    git(repo, "config", "user.name", "test")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "add", ".")
    git(repo, "commit", "--quiet", "-m", "base")
    return repo, git(repo, "rev-parse", "HEAD")


def write_log(tmp_path: Path, module: str) -> Path:
    log = tmp_path / "pytest.log"
    log.write_text(
        "ImportError while loading conftest '/work/backend/tests/conftest.py'.\n"
        f"E   ModuleNotFoundError: No module named '{module}'\n",
        encoding="utf-8",
    )
    return log


def test_base_declared_requirement_defers_collection_failure(tmp_path, capsys):
    module = load_module()
    repo, base_sha = make_repo(tmp_path, "fastapi==0.139.0\n")

    rc = module.main(
        [
            "--repo-root",
            str(repo),
            "--base-sha",
            base_sha,
            "--project-dir",
            "backend",
            "--pytest-exit",
            "4",
            "--log-file",
            str(write_log(tmp_path, "fastapi")),
        ]
    )

    assert rc == 0
    output = capsys.readouterr().out
    assert "DEFERRED" in output
    assert "backend/requirements.txt" in output


def test_undeclared_requirement_remains_blocking(tmp_path, capsys):
    module = load_module()
    repo, base_sha = make_repo(tmp_path, "pytest==9.1.1\n")

    rc = module.main(
        [
            "--repo-root",
            str(repo),
            "--base-sha",
            base_sha,
            "--project-dir",
            "backend",
            "--pytest-exit",
            "4",
            "--log-file",
            str(write_log(tmp_path, "fastapi")),
        ]
    )

    assert rc == 1
    assert "BLOCKING" in capsys.readouterr().out


def test_non_collection_failure_remains_blocking(tmp_path):
    module = load_module()
    repo, base_sha = make_repo(tmp_path, "fastapi==0.139.0\n")

    deferred, reason = module.classify(
        repo, base_sha, "backend", 1, write_log(tmp_path, "fastapi")
    )

    assert deferred is False
    assert "exit 1" in reason


def test_mixed_collection_exception_remains_blocking(tmp_path):
    module = load_module()
    repo, base_sha = make_repo(tmp_path, "fastapi==0.139.0\n")
    log = write_log(tmp_path, "fastapi")
    log.write_text(
        log.read_text(encoding="utf-8")
        + "E   SyntaxError: invalid syntax in tests/test_broken.py\n",
        encoding="utf-8",
    )

    deferred, reason = module.classify(repo, base_sha, "backend", 4, log)

    assert deferred is False
    assert "other exceptions: SyntaxError" in reason


def test_pull_request_only_dependency_does_not_change_base_decision(tmp_path):
    module = load_module()
    repo, base_sha = make_repo(tmp_path, "pytest==9.1.1\n")
    (repo / "backend" / "requirements.txt").write_text(
        "pytest==9.1.1\nfastapi==0.139.0\n", encoding="utf-8"
    )

    deferred, reason = module.classify(
        repo, base_sha, "backend", 4, write_log(tmp_path, "fastapi")
    )

    assert deferred is False
    assert "not base-declared" in reason


def test_pyproject_and_import_alias_are_supported(tmp_path):
    module = load_module()
    repo, base_sha = make_repo(
        tmp_path,
        '[project]\nname = "demo"\nversion = "1"\ndependencies = ["PyJWT==2.13.0"]\n',
        pyproject=True,
    )

    deferred, reason = module.classify(
        repo, base_sha, "backend", 4, write_log(tmp_path, "jwt")
    )

    assert deferred is True
    assert "pyjwt" in reason


def test_symlinked_log_remains_blocking(tmp_path):
    module = load_module()
    repo, base_sha = make_repo(tmp_path, "fastapi==0.139.0\n")
    real_log = write_log(tmp_path, "fastapi")
    linked_log = tmp_path / "linked.log"
    linked_log.symlink_to(real_log)

    deferred, reason = module.classify(repo, base_sha, "backend", 4, linked_log)

    assert deferred is False
    assert "not a regular file" in reason


def test_manifest_parsers_cover_supported_and_ignored_forms():
    module = load_module()

    assert module.validate_project_dir("") == "."
    with pytest.raises(ValueError, match="safe repository-relative"):
        module.validate_project_dir("/absolute")
    assert module.requirement_names("\n# comment\n-r base.txt\nFoo_Bar==1\n") == {
        "foo-bar"
    }
    assert module.pyproject_names("[project\ninvalid") == set()

    names = module.pyproject_names(
        """
[project]
optional-dependencies.test = ["Requests>=2"]
[tool.poetry.dependencies]
python = "^3.13"
Django = "^5"
[dependency-groups]
dev = ["ruff==0.14.13"]
"""
    )
    assert names == {"requests", "django", "ruff"}


def test_unbounded_or_non_dependency_collection_logs_remain_blocking(
    tmp_path, monkeypatch
):
    module = load_module()
    repo, base_sha = make_repo(tmp_path, "fastapi==0.139.0\n")
    log = tmp_path / "pytest.log"
    log.write_text("ERROR collecting tests/test_broken.py\n", encoding="utf-8")

    deferred, reason = module.classify(repo, base_sha, "backend", 4, log)

    assert deferred is False
    assert "did not name a missing Python module" in reason

    log = write_log(tmp_path, "fastapi")
    monkeypatch.setattr(module, "MAX_LOG_BYTES", 1)
    deferred, reason = module.classify(repo, base_sha, "backend", 4, log)

    assert deferred is False
    assert "size limit" in reason


def test_cli_rejects_untrusted_identity_and_paths(tmp_path):
    module = load_module()
    repo, base_sha = make_repo(tmp_path, "fastapi==0.139.0\n")
    log = write_log(tmp_path, "fastapi")

    def argv(*, sha=base_sha, project="backend", root=repo):
        return [
            "--repo-root",
            str(root),
            "--base-sha",
            sha,
            "--project-dir",
            project,
            "--pytest-exit",
            "4",
            "--log-file",
            str(log),
        ]

    with pytest.raises(SystemExit) as invalid_sha:
        module.parse_args(argv(sha="not-a-sha"))
    assert invalid_sha.value.code == 2

    with pytest.raises(SystemExit) as unsafe_project:
        module.parse_args(argv(project="../backend"))
    assert unsafe_project.value.code == 2

    non_repo = tmp_path / "not-a-repo"
    non_repo.mkdir()
    with pytest.raises(SystemExit) as invalid_repo:
        module.parse_args(argv(root=non_repo))
    assert invalid_repo.value.code == 2


def test_module_entrypoint_returns_deferred_exit(tmp_path, monkeypatch):
    repo, base_sha = make_repo(tmp_path, "fastapi==0.139.0\n")
    log = write_log(tmp_path, "fastapi")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(MODULE_PATH),
            "--repo-root",
            str(repo),
            "--base-sha",
            base_sha,
            "--project-dir",
            "backend",
            "--pytest-exit",
            "4",
            "--log-file",
            str(log),
        ],
    )

    with pytest.raises(SystemExit) as exit_info:
        runpy.run_path(str(MODULE_PATH), run_name="__main__")

    assert exit_info.value.code == 0
