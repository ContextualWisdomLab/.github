"""Tests for trusted npm workspace install-root resolution."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scripts.ci import npm_workspace_install_root as module
from scripts.ci.npm_workspace_install_root import ResolutionError, resolve_install_root


def _git(repo: Path, *args: str) -> str:
    """Run one fixture Git command and return stripped stdout."""
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return completed.stdout.strip()


def _init_repo(repo: Path) -> None:
    """Initialize a deterministic local Git repository for one test."""
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "tests@example.invalid")
    _git(repo, "config", "user.name", "Coverage Tests")


def _write_json(path: Path, payload: object) -> None:
    """Write deterministic JSON for one test fixture."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")


def _commit(repo: Path, message: str = "fixture") -> str:
    """Commit all fixture files and return the exact commit SHA."""
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _workspace(
    repo: Path,
    workspaces: object = None,
    *,
    intermediate: bool = False,
) -> tuple[Path, str]:
    """Create and commit a root npm workspace with one desktop package."""
    _init_repo(repo)
    root_manifest: dict[str, object] = {"name": "root", "private": True}
    root_manifest["workspaces"] = workspaces if workspaces is not None else ["apps/*"]
    _write_json(repo / "package.json", root_manifest)
    desktop = repo / "apps" / "desktop"
    _write_json(desktop / "package.json", {"name": "desktop"})
    _write_json(
        repo / "package-lock.json",
        {
            "name": "root",
            "lockfileVersion": 3,
            "packages": {"": {"name": "root"}, "apps/desktop": {"name": "desktop"}},
        },
    )
    if intermediate:
        _write_json(repo / "apps" / "package.json", {"name": "apps"})
        _write_json(
            repo / "apps" / "package-lock.json",
            {"name": "apps", "lockfileVersion": 3, "packages": {"": {}}},
        )
    return desktop, _commit(repo)


def _resolve(repo: Path, package: Path, base: str, head: str | None = None) -> str:
    """Call the production resolver with an optional distinct head SHA."""
    return resolve_install_root(repo, package, base, head or base)


def test_resolves_repository_root_for_nested_workspace(tmp_path: Path) -> None:
    """A nested workspace uses the ancestor repository-root npm lock."""
    desktop, revision = _workspace(tmp_path)
    assert _resolve(tmp_path, desktop, revision) == "."


def test_supports_object_valued_workspace_packages(tmp_path: Path) -> None:
    """npm's object form with a packages array is recognized."""
    desktop, revision = _workspace(tmp_path, {"packages": ["apps/*"]})
    assert _resolve(tmp_path, desktop, revision) == "."


def test_prefers_the_nearest_package_local_lock(tmp_path: Path) -> None:
    """A package-local lock takes precedence over an ancestor workspace lock."""
    desktop, base = _workspace(tmp_path)
    _write_json(
        desktop / "package-lock.json",
        {"name": "desktop", "lockfileVersion": 3, "packages": {"": {}}},
    )
    head = _commit(tmp_path, "local lock")
    assert _resolve(tmp_path, desktop, base, head) == "apps/desktop"


def test_skips_non_owner_intermediate_lock_and_checks_full_ancestry(
    tmp_path: Path,
) -> None:
    """An unrelated intermediate npm project does not hide the root workspace."""
    desktop, revision = _workspace(tmp_path, intermediate=True)
    assert _resolve(tmp_path, desktop, revision) == "."


def test_rejects_package_not_declared_by_any_workspace(tmp_path: Path) -> None:
    """An unrelated nested package cannot consume an ancestor lock cache."""
    desktop, revision = _workspace(tmp_path, ["packages/*"])
    with pytest.raises(ResolutionError, match="no validated package-lock"):
        _resolve(tmp_path, desktop, revision)


def test_rejects_package_missing_from_lock_map(tmp_path: Path) -> None:
    """Workspace declaration alone is insufficient without an exact lock entry."""
    desktop, _base = _workspace(tmp_path)
    lock = json.loads((tmp_path / "package-lock.json").read_text(encoding="utf-8"))
    del lock["packages"]["apps/desktop"]
    _write_json(tmp_path / "package-lock.json", lock)
    revision = _commit(tmp_path, "missing package entry")
    with pytest.raises(ResolutionError, match="no validated package-lock"):
        _resolve(tmp_path, desktop, revision)


@pytest.mark.parametrize(
    "pattern",
    [
        "",
        42,
        "!apps/*",
        "apps\\*",
        "/apps/*",
        "../apps/*",
        "node_modules/*",
        "apps/\x00*",
        "apps/**desktop",
        "apps/***",
        "apps/{desktop,web}",
        "apps/(desktop|web)",
        "apps/[desktop",
        "apps/desktop]",
    ],
)
def test_rejects_unsafe_workspace_patterns(tmp_path: Path, pattern: object) -> None:
    """Workspace patterns are constrained to safe relative path globs."""
    desktop, revision = _workspace(tmp_path, [pattern])
    with pytest.raises(ResolutionError, match="workspace pattern"):
        _resolve(tmp_path, desktop, revision)


@pytest.mark.parametrize(
    ("content", "match"),
    [("not-json", "invalid JSON"), ("[]", "must be a JSON object")],
)
def test_rejects_invalid_workspace_manifest(
    tmp_path: Path, content: str, match: str
) -> None:
    """Workspace ownership cannot be derived from malformed head JSON."""
    desktop, base = _workspace(tmp_path)
    (tmp_path / "package.json").write_text(content, encoding="utf-8")
    head = _commit(tmp_path, "bad manifest")
    with pytest.raises(ResolutionError, match=match):
        _resolve(tmp_path, desktop, base, head)


@pytest.mark.parametrize(
    ("payload", "match"),
    [
        ("not-json", "invalid JSON"),
        ("[]", "must be a JSON object"),
        (json.dumps({"packages": {"apps/desktop": {}}}), "lockfileVersion"),
        (json.dumps({"lockfileVersion": True, "packages": {}}), "lockfileVersion"),
        (json.dumps({"lockfileVersion": 3, "packages": []}), "packages object"),
    ],
)
def test_rejects_invalid_lock_metadata(
    tmp_path: Path, payload: str, match: str
) -> None:
    """Malformed lock metadata cannot establish npm ownership."""
    desktop, base = _workspace(tmp_path)
    (tmp_path / "package-lock.json").write_text(payload, encoding="utf-8")
    head = _commit(tmp_path, "bad lock")
    with pytest.raises(ResolutionError, match=match):
        _resolve(tmp_path, desktop, base, head)


def test_rejects_package_directory_escape(tmp_path: Path) -> None:
    """The requested package must remain beneath the validated repository root."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write_json(repo / "package.json", {"name": "repo"})
    revision = _commit(repo)
    outside = tmp_path / "outside"
    _write_json(outside / "package.json", {"name": "outside"})
    with pytest.raises(ResolutionError, match="escaped"):
        _resolve(repo, outside, revision)


def test_rejects_symlinked_package_directory(tmp_path: Path) -> None:
    """A symlink cannot redirect package reads inside or outside the tree."""
    repo = tmp_path / "repo"
    desktop, revision = _workspace(repo)
    link = repo / "linked"
    try:
        link.symlink_to(desktop, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")
    with pytest.raises(ResolutionError, match="symlink"):
        _resolve(repo, link, revision)


def test_rejects_repository_root_symlink(tmp_path: Path) -> None:
    """The trusted repository root cannot be redirected through a symlink."""
    real_root = tmp_path / "real"
    _workspace(real_root)
    link = tmp_path / "link"
    try:
        link.symlink_to(real_root, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")
    with pytest.raises(ResolutionError, match="repository root"):
        _resolve(link, real_root / "apps" / "desktop", "0" * 40)


def test_rejects_repository_root_that_is_a_file(tmp_path: Path) -> None:
    """The repository root must be a real directory."""
    root_file = tmp_path / "repo"
    root_file.write_text("not a directory", encoding="utf-8")
    with pytest.raises(ResolutionError, match="repository root"):
        _resolve(root_file, root_file, "0" * 40)


def test_rejects_package_path_that_is_a_file(tmp_path: Path) -> None:
    """The package path itself must be a directory."""
    repo = tmp_path / "repo"
    desktop, revision = _workspace(repo)
    package_file = desktop / "package.json"
    with pytest.raises(ResolutionError, match="package directory"):
        _resolve(repo, package_file, revision)


def test_rejects_missing_selected_package_manifest(tmp_path: Path) -> None:
    """The selected package must have a package manifest at validated head."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    package = repo / "apps" / "desktop"
    package.mkdir(parents=True)
    _write_json(repo / "package.json", {"name": "root", "workspaces": ["apps/*"]})
    _write_json(
        repo / "package-lock.json",
        {"lockfileVersion": 3, "packages": {"apps/desktop": {}}},
    )
    revision = _commit(repo)
    with pytest.raises(ResolutionError, match="absent from validated head"):
        _resolve(repo, package, revision)


def test_rejects_tree_without_any_npm_lock(tmp_path: Path) -> None:
    """Walking the full ancestor chain without an owning lock fails closed."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    package = repo / "apps" / "desktop"
    _write_json(package / "package.json", {"name": "desktop"})
    revision = _commit(repo)
    with pytest.raises(ResolutionError, match="no validated package-lock"):
        _resolve(repo, package, revision)


def test_accepts_lock_added_only_at_head_for_receipt_validation(tmp_path: Path) -> None:
    """A head-added lock may own the package when the workflow authenticates it."""
    desktop, _initial = _workspace(tmp_path)
    (tmp_path / "package-lock.json").unlink()
    base = _commit(tmp_path, "remove lock")
    _write_json(
        tmp_path / "package-lock.json",
        {
            "lockfileVersion": 3,
            "packages": {"": {}, "apps/desktop": {}},
        },
    )
    head = _commit(tmp_path, "add bounded head lock")
    assert _resolve(tmp_path, desktop, base, head) == "."


def test_accepts_bounded_lock_change_between_base_and_head(tmp_path: Path) -> None:
    """A changed head lock remains eligible for exact manifest-receipt checks."""
    desktop, base = _workspace(tmp_path)
    lock = json.loads((tmp_path / "package-lock.json").read_text(encoding="utf-8"))
    lock["packages"]["apps/desktop"]["version"] = "1.0.0"
    _write_json(tmp_path / "package-lock.json", lock)
    head = _commit(tmp_path, "change lock")
    assert _resolve(tmp_path, desktop, base, head) == "."


def test_accepts_workspace_manifest_change_at_validated_head(tmp_path: Path) -> None:
    """Ownership follows the live head declaration rather than stale base JSON."""
    desktop, base = _workspace(tmp_path, ["packages/*"])
    _write_json(
        tmp_path / "package.json",
        {"name": "root", "private": True, "workspaces": ["apps/*", "packages/*"]},
    )
    head = _commit(tmp_path, "change workspaces")
    assert _resolve(tmp_path, desktop, base, head) == "."


def test_accepts_pr_added_workspace_package_in_head_lock_map(tmp_path: Path) -> None:
    """A new workspace package is valid when head manifest and lock agree."""
    _init_repo(tmp_path)
    _write_json(
        tmp_path / "package.json",
        {"name": "root", "private": True, "workspaces": ["packages/*"]},
    )
    _write_json(
        tmp_path / "package-lock.json",
        {"lockfileVersion": 3, "packages": {"": {}}},
    )
    base = _commit(tmp_path, "base")
    desktop = tmp_path / "apps" / "desktop"
    _write_json(desktop / "package.json", {"name": "desktop"})
    _write_json(
        tmp_path / "package.json",
        {"name": "root", "private": True, "workspaces": ["apps/*", "packages/*"]},
    )
    _write_json(
        tmp_path / "package-lock.json",
        {"lockfileVersion": 3, "packages": {"": {}, "apps/desktop": {}}},
    )
    head = _commit(tmp_path, "add workspace")
    assert _resolve(tmp_path, desktop, base, head) == "."


def test_rejects_worktree_lock_that_differs_from_validated_head(tmp_path: Path) -> None:
    """Mutable worktree lock content cannot replace the validated head blob."""
    desktop, revision = _workspace(tmp_path)
    (tmp_path / "package-lock.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(ResolutionError, match="does not match the validated head"):
        _resolve(tmp_path, desktop, revision)


def test_rejects_worktree_manifest_that_differs_from_validated_head(
    tmp_path: Path,
) -> None:
    """Mutable worktree manifest content cannot influence ownership."""
    desktop, revision = _workspace(tmp_path)
    (tmp_path / "package.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(ResolutionError, match="does not match the validated head"):
        _resolve(tmp_path, desktop, revision)


def test_rejects_invalid_or_missing_revision(tmp_path: Path) -> None:
    """Only exact existing commit SHAs can anchor resolver evidence."""
    desktop, revision = _workspace(tmp_path)
    with pytest.raises(ResolutionError, match="40 hexadecimal"):
        _resolve(tmp_path, desktop, "main", revision)
    with pytest.raises(ResolutionError, match="git cat-file failed"):
        _resolve(tmp_path, desktop, "f" * 40, revision)


def test_main_prints_resolved_root(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """The command-line entry point prints the validated install root."""
    desktop, revision = _workspace(tmp_path)
    assert (
        module.main(
            [
                "--repo-root",
                str(tmp_path),
                "--package-dir",
                str(desktop),
                "--base-sha",
                revision,
                "--head-sha",
                revision,
            ]
        )
        == 0
    )
    assert capsys.readouterr().out == ".\n"


def test_main_reports_resolution_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The CLI turns fail-closed resolver errors into parser errors."""
    desktop, revision = _workspace(tmp_path)
    (tmp_path / "package-lock.json").unlink()
    with pytest.raises(SystemExit, match="2"):
        module.main(
            [
                "--repo-root",
                str(tmp_path),
                "--package-dir",
                str(desktop),
                "--base-sha",
                revision,
                "--head-sha",
                revision,
            ]
        )
    assert "regular non-symlink file" in capsys.readouterr().err


def test_rejects_missing_package_directory(tmp_path: Path) -> None:
    """A nonexistent selected package path fails before Git evidence is read."""
    repo = tmp_path / "repo"
    desktop, revision = _workspace(repo)
    missing = desktop / "missing"
    with pytest.raises(ResolutionError, match="does not exist"):
        _resolve(repo, missing, revision)


def test_rejects_missing_repository_root(tmp_path: Path) -> None:
    """A nonexistent repository root fails with a bounded root diagnostic."""
    missing = tmp_path / "missing"
    with pytest.raises(ResolutionError, match="repository root"):
        _resolve(missing, missing, "0" * 40)


def test_rejects_lock_owner_without_manifest(tmp_path: Path) -> None:
    """A lock cannot establish ownership without a regular owner manifest."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    package = repo / "apps" / "desktop"
    _write_json(package / "package.json", {"name": "desktop"})
    _write_json(
        repo / "package-lock.json",
        {"lockfileVersion": 3, "packages": {"apps/desktop": {}}},
    )
    revision = _commit(repo)
    with pytest.raises(ResolutionError, match="lock owner manifest"):
        _resolve(repo, package, revision)


def test_rejects_root_local_lock_without_root_package_entry(tmp_path: Path) -> None:
    """A package-local root lock must cover its own empty package-map key."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write_json(repo / "package.json", {"name": "root"})
    _write_json(
        repo / "package-lock.json",
        {"lockfileVersion": 3, "packages": {"other": {}}},
    )
    revision = _commit(repo)
    with pytest.raises(ResolutionError, match="no validated package-lock"):
        _resolve(repo, repo, revision)


@pytest.mark.parametrize(
    ("git_output", "match"),
    [
        (
            b"100644 blob aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\tpackage.json\0"
            b"100644 blob bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\tpackage.json\0",
            "multiple Git tree entries",
        ),
        (b"malformed\tpackage.json\0", "malformed Git tree metadata"),
        (
            b"100644 blob aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\tother.json\0",
            "path did not match exactly",
        ),
        (
            b"120000 blob aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\tpackage.json\0",
            "regular non-symlink Git blob",
        ),
    ],
)
def test_tree_blob_rejects_malformed_or_unsafe_git_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    git_output: bytes,
    match: str,
) -> None:
    """Git tree evidence must be singular, exact, and regular-file metadata."""
    monkeypatch.setattr(module, "_git", lambda *_args: git_output)
    with pytest.raises(ResolutionError, match=match):
        module._tree_blob(
            tmp_path,
            "a" * 40,
            module.PurePosixPath("package.json"),
            "fixture manifest",
        )
