from __future__ import annotations

import json
import runpy
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.ci import materialize_base_javascript_packages as materializer


def git(repo: Path, *args: str) -> str:
    """Run git in a temporary fixture repository."""
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def fixture_repo(tmp_path: Path) -> tuple[Path, str]:
    """Create a repository whose head mutates the trusted base package inputs."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "user.name", "Test")
    git(repo, "config", "user.email", "test@example.invalid")

    frontend = repo / "frontend"
    frontend.mkdir()
    (frontend / "package.json").write_text(
        json.dumps({"packageManager": "pnpm@11.5.3"}) + "\n",
        encoding="utf-8",
    )
    (frontend / "pnpm-lock.yaml").write_text(
        "lockfileVersion: '9.0'\n"
        "patchedDependencies:\n"
        "  base@1.0.0: base-hash\n"
        "packages:\n"
        "  base@1.0.0: {}\n",
        encoding="utf-8",
    )
    (frontend / "pnpm-workspace.yaml").write_text(
        "patchedDependencies:\n  base@1.0.0: patches/base.patch\n",
        encoding="utf-8",
    )
    (frontend / ".pnpmfile.cjs").write_text(
        "module.exports = { hooks: {} };\n",
        encoding="utf-8",
    )
    patches = frontend / "patches"
    patches.mkdir()
    (patches / "base.patch").write_text("trusted base patch\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "base")
    base_sha = git(repo, "rev-parse", "HEAD")

    (frontend / "package.json").write_text(
        json.dumps({"packageManager": "pnpm@99.0.0"}) + "\n",
        encoding="utf-8",
    )
    (frontend / "pnpm-lock.yaml").write_text(
        "lockfileVersion: '9.0'\npackages:\n  head@2.0.0: {}\n",
        encoding="utf-8",
    )
    (frontend / "pnpm-workspace.yaml").write_text(
        "patchedDependencies:\n  head@2.0.0: patches/head.patch\n",
        encoding="utf-8",
    )
    (frontend / ".pnpmfile.cjs").write_text(
        "throw new Error('untrusted head hook');\n",
        encoding="utf-8",
    )
    (patches / "base.patch").unlink()
    (patches / "head.patch").write_text("untrusted head patch\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "head")
    return repo, base_sha


def test_materializes_only_exact_base_pnpm_inputs(tmp_path: Path) -> None:
    """PR-modified package metadata cannot enter the networked build context."""
    repo, base_sha = fixture_repo(tmp_path)
    output = tmp_path / "output"

    manifest = materializer.materialize(repo, base_sha, output)

    assert manifest == [
        {
            "directory": "project-000",
            "package_manager": "pnpm@11.5.3",
            "source": "frontend/pnpm-lock.yaml",
        }
    ]
    assert "base@1.0.0" in (output / "project-000" / "pnpm-lock.yaml").read_text(
        encoding="utf-8"
    )
    assert "head@2.0.0" not in (output / "project-000" / "pnpm-lock.yaml").read_text(
        encoding="utf-8"
    )
    assert (output / "project-000" / "package.json").read_text(
        encoding="utf-8"
    ) == '{"packageManager": "pnpm@11.5.3"}\n'
    assert "base@1.0.0" in (output / "project-000" / "pnpm-workspace.yaml").read_text(
        encoding="utf-8"
    )
    assert "hooks: {}" in (output / "project-000" / ".pnpmfile.cjs").read_text(
        encoding="utf-8"
    )
    assert (output / "project-000" / "patches" / "base.patch").read_text(
        encoding="utf-8"
    ) == "trusted base patch\n"
    assert not (output / "project-000" / "patches" / "head.patch").exists()
    assert (
        json.loads((output / "manifest.json").read_text(encoding="utf-8")) == manifest
    )


def test_rejects_invalid_base_sha(tmp_path: Path) -> None:
    """Git options and symbolic refs cannot cross the exact-SHA boundary."""
    with pytest.raises(ValueError, match="40 hexadecimal"):
        materializer.base_pnpm_projects(tmp_path, "--help")


def test_git_failure_preserves_command_reason(tmp_path: Path) -> None:
    """Read-only git failures retain the actionable stderr detail."""
    with pytest.raises(RuntimeError, match="git rev-parse failed"):
        materializer._git(tmp_path, "rev-parse", "HEAD")


@pytest.mark.parametrize(
    ("tree_output", "message"),
    [
        (b"malformed\0", "malformed entry"),
        (b"100644 blob\tfile\0", "malformed metadata"),
    ],
)
def test_rejects_malformed_git_tree_entries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tree_output: bytes,
    message: str,
) -> None:
    """Malformed git output cannot be interpreted as trusted base input."""

    def fake_git(_repo_root: Path, *_args: str) -> bytes:
        return tree_output

    monkeypatch.setattr(materializer, "_git", fake_git)
    with pytest.raises(RuntimeError, match=message):
        materializer.base_pnpm_projects(tmp_path, "a" * 40)


def test_rejects_lock_without_sibling_package_manifest(tmp_path: Path) -> None:
    """A lock without an exact package-manager declaration fails closed."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "user.name", "Test")
    git(repo, "config", "user.email", "test@example.invalid")
    (repo / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "base")

    with pytest.raises(ValueError, match="no regular sibling package.json"):
        materializer.base_pnpm_projects(repo, git(repo, "rev-parse", "HEAD"))


@pytest.mark.parametrize(
    ("package_content", "lock_content", "message"),
    [
        (b"not-json", b"lockfileVersion: '9.0'\n", "invalid JSON"),
        (b"[]", b"lockfileVersion: '9.0'\n", "must be a JSON object"),
        (
            b'{"packageManager":"pnpm@11.5.3"}',
            b"\n",
            "pnpm lock frontend/pnpm-lock.yaml is empty",
        ),
    ],
)
def test_rejects_invalid_base_package_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    package_content: bytes,
    lock_content: bytes,
    message: str,
) -> None:
    """Malformed base manifests and empty locks fail before materialization."""
    regular_paths = {"frontend/package.json", "frontend/pnpm-lock.yaml"}
    monkeypatch.setattr(
        materializer,
        "_regular_base_paths",
        lambda *_args: regular_paths,
    )

    def fake_git(_repo_root: Path, _command: str, object_spec: str) -> bytes:
        if object_spec.endswith(":frontend/package.json"):
            return package_content
        if object_spec.endswith(":frontend/pnpm-lock.yaml"):
            return lock_content
        raise AssertionError(f"unexpected git object: {object_spec}")

    monkeypatch.setattr(materializer, "_git", fake_git)
    with pytest.raises(ValueError, match=message):
        materializer.base_pnpm_projects(tmp_path, "a" * 40)


def test_skips_npm_project_with_vestigial_pnpm_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An npm project's stray pnpm-lock.yaml is skipped, not fail-closed.

    A base tree with a ``pnpm-lock.yaml`` plus a sibling ``package-lock.json``
    and no exact pnpm ``packageManager`` is npm-managed, so pnpm materialization
    is skipped (the downstream npm install path owns it) rather than failing the
    whole coverage-evidence job.
    """
    regular_paths = {
        "frontend/package.json",
        "frontend/pnpm-lock.yaml",
        "frontend/package-lock.json",
    }
    monkeypatch.setattr(
        materializer, "_regular_base_paths", lambda *_args: regular_paths
    )

    def fake_git(_repo_root: Path, _command: str, object_spec: str) -> bytes:
        if object_spec.endswith(":frontend/package.json"):
            return b"{}"
        raise AssertionError(f"unexpected git object: {object_spec}")

    monkeypatch.setattr(materializer, "_git", fake_git)
    assert materializer.base_pnpm_projects(tmp_path, "a" * 40) == []


def test_rejects_mutable_or_non_pnpm_package_manager(tmp_path: Path) -> None:
    """Only an exact pnpm runner specification may populate the trusted store."""
    repo, base_sha = fixture_repo(tmp_path)
    base_package = repo / "frontend" / "package.json"
    git(repo, "checkout", base_sha, "--", "frontend/package.json")
    base_package.write_text(
        json.dumps({"packageManager": "pnpm@latest"}) + "\n", encoding="utf-8"
    )
    git(repo, "add", ".")
    git(repo, "commit", "-m", "mutable base")

    with pytest.raises(ValueError, match="exact pnpm packageManager"):
        materializer.base_pnpm_projects(repo, git(repo, "rev-parse", "HEAD"))


def test_rejects_symlink_output_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A symlink cannot redirect trusted materialization outside its context."""
    target = tmp_path / "target"
    target.mkdir()
    output = tmp_path / "output"
    output.symlink_to(target, target_is_directory=True)
    monkeypatch.setattr(materializer, "base_pnpm_projects", lambda *_args: [])

    with pytest.raises(ValueError, match="must not be a symlink"):
        materializer.materialize(tmp_path, "a" * 40, output)


def test_main_reports_materialized_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The CLI identifies the exact trusted base source and runner."""
    monkeypatch.setattr(
        materializer,
        "materialize",
        lambda *_args: [
            {
                "directory": "project-000",
                "package_manager": "pnpm@11.5.3",
                "source": "frontend/pnpm-lock.yaml",
            }
        ],
    )

    assert (
        materializer.main(
            [
                "--repo-root",
                str(tmp_path),
                "--base-sha",
                "a" * 40,
                "--output-dir",
                str(tmp_path / "output"),
            ]
        )
        == 0
    )
    assert (
        "Materialized trusted base pnpm lock frontend/pnpm-lock.yaml "
        "for pnpm@11.5.3 as project-000/pnpm-lock.yaml." in capsys.readouterr().out
    )


def test_main_reports_empty_base(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The CLI distinguishes an empty trusted base from extraction failure."""
    monkeypatch.setattr(materializer, "materialize", lambda *_args: [])
    assert (
        materializer.main(
            [
                "--repo-root",
                str(tmp_path),
                "--base-sha",
                "a" * 40,
                "--output-dir",
                str(tmp_path / "output"),
            ]
        )
        == 0
    )
    assert "No tracked pnpm-lock.yaml files exist" in capsys.readouterr().out


def test_main_preserves_failure_reason(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Materialization failures remain diagnosable and fail closed."""

    def fail_materialize(_repo_root: Path, _base_sha: str, _output_dir: Path) -> None:
        raise OSError("fixture failure")

    monkeypatch.setattr(materializer, "materialize", fail_materialize)
    assert (
        materializer.main(
            [
                "--repo-root",
                str(tmp_path),
                "--base-sha",
                "a" * 40,
                "--output-dir",
                str(tmp_path / "output"),
            ]
        )
        == 1
    )
    assert (
        "::error::Could not materialize base JavaScript package locks: fixture failure"
        in capsys.readouterr().err
    )


def test_script_entrypoint_exits_through_main(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The executable script propagates the fail-closed CLI status."""
    module_path = Path(materializer.__file__)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(module_path),
            "--repo-root",
            str(tmp_path),
            "--base-sha",
            "invalid",
            "--output-dir",
            str(tmp_path / "output"),
        ],
    )
    with pytest.raises(SystemExit) as raised:
        runpy.run_path(str(module_path), run_name="__main__")
    assert raised.value.code == 1
