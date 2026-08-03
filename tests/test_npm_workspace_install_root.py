"""Tests for trusted npm workspace install-root resolution."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.ci.npm_workspace_install_root import resolve_install_root


def _write_json(path: Path, payload: object) -> None:
    """Write deterministic JSON for one test fixture."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")


def _workspace(repo: Path, workspaces: object = None) -> Path:
    """Create a root npm project and one nested desktop package."""
    root_manifest: dict[str, object] = {"name": "root", "private": True}
    root_manifest["workspaces"] = workspaces or ["apps/*", "packages/*"]
    _write_json(repo / "package.json", root_manifest)
    desktop = repo / "apps" / "desktop"
    _write_json(desktop / "package.json", {"name": "desktop"})
    _write_json(
        repo / "package-lock.json",
        {
            "name": "root",
            "lockfileVersion": 3,
            "packages": {
                "": {"name": "root", "workspaces": ["apps/*", "packages/*"]},
                "apps/desktop": {"name": "desktop"},
            },
        },
    )
    return desktop


def test_resolves_repository_root_for_nested_workspace(tmp_path: Path) -> None:
    """A nested workspace uses the ancestor's repository-root npm lock."""
    desktop = _workspace(tmp_path)
    assert resolve_install_root(tmp_path, desktop) == "."


def test_supports_object_valued_workspace_packages(tmp_path: Path) -> None:
    """npm's object form with a packages array is recognized."""
    desktop = _workspace(tmp_path, {"packages": ["apps/*"]})
    assert resolve_install_root(tmp_path, desktop) == "."


def test_prefers_the_nearest_lock_owner(tmp_path: Path) -> None:
    """A package-local lock takes precedence over an ancestor workspace lock."""
    desktop = _workspace(tmp_path)
    _write_json(
        desktop / "package-lock.json",
        {"name": "desktop", "lockfileVersion": 3, "packages": {"": {}}},
    )
    assert resolve_install_root(tmp_path, desktop) == "apps/desktop"


def test_rejects_package_not_declared_by_workspace(tmp_path: Path) -> None:
    """An unrelated nested package cannot consume an ancestor lock/cache."""
    desktop = _workspace(tmp_path, ["packages/*"])
    with pytest.raises(ValueError, match="not declared"):
        resolve_install_root(tmp_path, desktop)


def test_rejects_package_missing_from_lock_map(tmp_path: Path) -> None:
    """Workspace declaration alone is insufficient without an exact lock entry."""
    desktop = _workspace(tmp_path)
    lock = json.loads((tmp_path / "package-lock.json").read_text(encoding="utf-8"))
    del lock["packages"]["apps/desktop"]
    _write_json(tmp_path / "package-lock.json", lock)
    with pytest.raises(ValueError, match="does not contain workspace package"):
        resolve_install_root(tmp_path, desktop)


def test_rejects_parent_traversal_workspace_pattern(tmp_path: Path) -> None:
    """A workspace pattern cannot escape the trusted lock-owner directory."""
    desktop = _workspace(tmp_path, ["../apps/*"])
    with pytest.raises(ValueError, match="unsafe npm workspace pattern"):
        resolve_install_root(tmp_path, desktop)


def test_rejects_package_directory_escape(tmp_path: Path) -> None:
    """The requested package must remain beneath the validated repository root."""
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside"
    _write_json(outside / "package.json", {"name": "outside"})
    with pytest.raises(ValueError, match="escaped"):
        resolve_install_root(repo, outside)


def test_rejects_symlinked_package_directory(tmp_path: Path) -> None:
    """A symlink cannot redirect package reads outside the validated tree."""
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside"
    _write_json(outside / "package.json", {"name": "outside"})
    link = repo / "linked"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")
    with pytest.raises(ValueError, match="escaped|non-symlink"):
        resolve_install_root(repo, link)


def test_rejects_missing_package_manifest(tmp_path: Path) -> None:
    """Every selected package must own a regular package manifest."""
    package = tmp_path / "apps" / "desktop"
    package.mkdir(parents=True)
    with pytest.raises(ValueError, match="package manifest"):
        resolve_install_root(tmp_path, package)


@pytest.mark.parametrize(
    ("root_manifest", "match"),
    [
        ("not-json", "invalid JSON"),
        ("[]", "must be a JSON object"),
        (json.dumps({"name": "root"}), "not declared"),
    ],
)
def test_rejects_invalid_or_missing_workspace_declaration(
    tmp_path: Path, root_manifest: str, match: str
) -> None:
    """Ancestor workspace metadata must be valid JSON and declare the package."""
    desktop = _workspace(tmp_path)
    (tmp_path / "package.json").write_text(root_manifest, encoding="utf-8")
    with pytest.raises(ValueError, match=match):
        resolve_install_root(tmp_path, desktop)


@pytest.mark.parametrize("pattern", ["", 42, "apps\\*", "/apps/*", "node_modules/*"])
def test_rejects_malformed_workspace_patterns(tmp_path: Path, pattern: object) -> None:
    """Workspace patterns are constrained to safe repository-relative strings."""
    desktop = _workspace(tmp_path, [pattern])
    with pytest.raises(ValueError, match="workspace pattern"):
        resolve_install_root(tmp_path, desktop)


def test_rejects_invalid_lock_json(tmp_path: Path) -> None:
    """An ancestor npm lock must be a JSON object before its package map is used."""
    desktop = _workspace(tmp_path)
    (tmp_path / "package-lock.json").write_text("not-json", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid JSON"):
        resolve_install_root(tmp_path, desktop)


def test_rejects_non_object_lock_json(tmp_path: Path) -> None:
    """An ancestor npm lock cannot use a non-object JSON root."""
    desktop = _workspace(tmp_path)
    (tmp_path / "package-lock.json").write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="must be a JSON object"):
        resolve_install_root(tmp_path, desktop)


def test_rejects_repository_root_that_is_a_file(tmp_path: Path) -> None:
    """The repository root must be a directory."""
    root_file = tmp_path / "repo"
    root_file.write_text("not a directory", encoding="utf-8")
    package = tmp_path / "package"
    _write_json(package / "package.json", {"name": "package"})
    with pytest.raises(ValueError, match="repository root"):
        resolve_install_root(root_file, package)


def test_rejects_package_path_that_is_a_file(tmp_path: Path) -> None:
    """The package path itself must be a directory."""
    package_file = tmp_path / "package.json"
    package_file.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="package directory"):
        resolve_install_root(tmp_path, package_file)


def test_rejects_repository_root_symlink(tmp_path: Path) -> None:
    """The trusted repository root cannot be redirected through a symlink."""
    real_root = tmp_path / "real"
    real_root.mkdir()
    link = tmp_path / "link"
    try:
        link.symlink_to(real_root, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")
    with pytest.raises(ValueError, match="repository root"):
        resolve_install_root(link, real_root)


def test_rejects_tree_without_any_npm_lock(tmp_path: Path) -> None:
    """Walking to the repository root without finding a lock fails closed."""
    package = tmp_path / "apps" / "desktop"
    _write_json(package / "package.json", {"name": "desktop"})
    with pytest.raises(ValueError, match="no regular package-lock"):
        resolve_install_root(tmp_path, package)


def test_main_prints_resolved_root(tmp_path: Path, monkeypatch, capsys) -> None:
    """The command-line entry point prints the validated relative install root."""
    from scripts.ci import npm_workspace_install_root as module

    desktop = _workspace(tmp_path)
    monkeypatch.setattr(
        "sys.argv",
        [
            "npm_workspace_install_root.py",
            "--repo-root",
            str(tmp_path),
            "--package-dir",
            str(desktop),
        ],
    )
    assert module.main() == 0
    assert capsys.readouterr().out == ".\n"


def test_main_reports_resolution_error(tmp_path: Path, monkeypatch, capsys) -> None:
    """The command-line entry point turns resolver failures into parser errors."""
    from scripts.ci import npm_workspace_install_root as module

    package = tmp_path / "apps" / "desktop"
    _write_json(package / "package.json", {"name": "desktop"})
    monkeypatch.setattr(
        "sys.argv",
        [
            "npm_workspace_install_root.py",
            "--repo-root",
            str(tmp_path),
            "--package-dir",
            str(package),
        ],
    )
    with pytest.raises(SystemExit, match="2"):
        module.main()
    assert "no regular package-lock" in capsys.readouterr().err
