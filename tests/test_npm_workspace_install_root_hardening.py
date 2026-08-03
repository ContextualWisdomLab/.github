"""Hardening tests for trusted npm workspace install-root resolution."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scripts.ci import npm_workspace_install_root as module
from scripts.ci.npm_workspace_install_root import ResolutionError, resolve_install_root


def _git(repo: Path, *args: str) -> str:
    """Run one fixture Git command and return stripped standard output."""
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return completed.stdout.strip()


def _write_json(path: Path, payload: object) -> None:
    """Write deterministic UTF-8 JSON for a fixture file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")


def _commit(repo: Path, message: str = "fixture") -> str:
    """Commit every fixture path and return the exact revision SHA."""
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _workspace_repo(
    repo: Path,
    *,
    package_path: str = "apps/desktop",
    patterns: object = None,
    lockfile_version: object = 3,
) -> tuple[Path, str]:
    """Create a committed npm workspace fixture with one selected package."""
    repo.mkdir(parents=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "tests@example.invalid")
    _git(repo, "config", "user.name", "Coverage Tests")
    declared_patterns = ["apps/*", "packages/*"] if patterns is None else patterns
    _write_json(
        repo / "package.json",
        {"name": "root", "private": True, "workspaces": declared_patterns},
    )
    package = repo.joinpath(*package_path.split("/"))
    _write_json(package / "package.json", {"name": package.name})
    _write_json(
        repo / "package-lock.json",
        {
            "name": "root",
            "lockfileVersion": lockfile_version,
            "packages": {"": {"name": "root"}, package_path: {"name": package.name}},
        },
    )
    return package, _commit(repo)


def test_resolves_bandscope_apps_desktop_layout(tmp_path: Path) -> None:
    """BandScope's root workspaces and apps/desktop package resolve to root."""
    package, revision = _workspace_repo(tmp_path)
    assert resolve_install_root(tmp_path, package, revision, revision) == "."


def test_single_star_never_authorizes_multiple_path_segments(tmp_path: Path) -> None:
    """A single-star workspace segment cannot consume a deeper package path."""
    package, revision = _workspace_repo(
        tmp_path,
        package_path="apps/deep/desktop",
        patterns=["apps/*"],
    )
    with pytest.raises(ResolutionError, match="no validated package-lock"):
        resolve_install_root(tmp_path, package, revision, revision)


def test_double_star_authorizes_multiple_repository_path_segments(tmp_path: Path) -> None:
    """A whole-segment double star may match one or more nested path segments."""
    package, revision = _workspace_repo(
        tmp_path,
        package_path="apps/deep/desktop",
        patterns=["apps/**"],
    )
    assert resolve_install_root(tmp_path, package, revision, revision) == "."


@pytest.mark.parametrize("pattern", ["apps/**desktop", "apps/***", "apps/{desktop,web}"])
def test_rejects_ambiguous_workspace_glob_syntax(
    tmp_path: Path,
    pattern: str,
) -> None:
    """Unsupported glob constructs fail closed instead of broadening ownership."""
    package, revision = _workspace_repo(tmp_path, patterns=[pattern])
    with pytest.raises(ResolutionError, match="workspace pattern"):
        resolve_install_root(tmp_path, package, revision, revision)


@pytest.mark.parametrize("workspaces", [[], {"packages": []}])
def test_empty_workspace_declaration_does_not_authorize_package(
    tmp_path: Path,
    workspaces: object,
) -> None:
    """An explicit empty workspace declaration remains empty and fails closed."""
    package, revision = _workspace_repo(tmp_path, patterns=workspaces)
    with pytest.raises(ResolutionError, match="no validated package-lock"):
        resolve_install_root(tmp_path, package, revision, revision)


@pytest.mark.parametrize("version", [-1, 0, 1, 4, True, "3"])
def test_rejects_unsupported_or_malformed_lockfile_versions(
    tmp_path: Path,
    version: object,
) -> None:
    """Only npm lockfile versions with an authenticated packages map are accepted."""
    package, revision = _workspace_repo(tmp_path, lockfile_version=version)
    with pytest.raises(ResolutionError, match="lockfileVersion"):
        resolve_install_root(tmp_path, package, revision, revision)


def test_rejects_non_object_exact_workspace_lock_entry(tmp_path: Path) -> None:
    """The exact workspace entry must be a JSON object, not merely present."""
    package, _revision = _workspace_repo(tmp_path)
    lock_path = tmp_path / "package-lock.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    lock["packages"]["apps/desktop"] = None
    _write_json(lock_path, lock)
    revision = _commit(tmp_path, "non-object workspace entry")
    with pytest.raises(ResolutionError, match="no validated package-lock"):
        resolve_install_root(tmp_path, package, revision, revision)


def test_npm_shrinkwrap_takes_precedence_over_package_lock(tmp_path: Path) -> None:
    """An existing shrinkwrap is authoritative even when package-lock is valid."""
    package, _revision = _workspace_repo(tmp_path)
    _write_json(
        tmp_path / "npm-shrinkwrap.json",
        {
            "name": "root",
            "lockfileVersion": 3,
            "packages": {"": {"name": "root"}},
        },
    )
    revision = _commit(tmp_path, "authoritative shrinkwrap")
    with pytest.raises(ResolutionError, match="no validated package-lock"):
        resolve_install_root(tmp_path, package, revision, revision)


def test_rejects_symlink_in_existing_package_ancestor(tmp_path: Path) -> None:
    """Every existing path component from repository root to package is real."""
    repo = tmp_path / "repo"
    outside = tmp_path / "outside"
    outside_package = outside / "desktop"
    _write_json(outside_package / "package.json", {"name": "desktop"})
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "tests@example.invalid")
    _git(repo, "config", "user.name", "Coverage Tests")
    _write_json(repo / "package.json", {"name": "root", "workspaces": ["apps/*"]})
    _write_json(
        repo / "package-lock.json",
        {
            "lockfileVersion": 3,
            "packages": {"": {}, "apps/desktop": {"name": "desktop"}},
        },
    )
    (repo / "apps").mkdir()
    _write_json(repo / "apps" / "desktop" / "package.json", {"name": "desktop"})
    revision = _commit(repo)
    subprocess.run(["rm", "-rf", str(repo / "apps")], check=True)
    try:
        (repo / "apps").symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")
    with pytest.raises(ResolutionError, match="symlink"):
        resolve_install_root(repo, repo / "apps" / "desktop", revision, revision)


def test_cli_rejects_control_characters_in_resolver_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The command line never emits a path containing controls or extra lines."""
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr(module, "resolve_install_root", lambda *_args: "apps/desktop\nforged")
    with pytest.raises(SystemExit, match="2"):
        module.main(
            [
                "--repo-root",
                str(repo),
                "--package-dir",
                str(repo),
                "--base-sha",
                "0" * 40,
                "--head-sha",
                "0" * 40,
            ]
        )
