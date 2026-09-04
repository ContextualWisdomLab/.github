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


def npm_fixture_repo(tmp_path: Path) -> tuple[Path, str]:
    """Create an npm workspace whose head mutates all trusted package inputs."""
    repo = tmp_path / "npm-repo"
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "user.name", "Test")
    git(repo, "config", "user.email", "test@example.invalid")

    workspace = repo / "packages" / "worker"
    workspace.mkdir(parents=True)
    (repo / "package.json").write_text(
        json.dumps(
            {
                "name": "trusted-base",
                "private": True,
                "workspaces": ["packages/*"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (workspace / "package.json").write_text(
        json.dumps({"name": "@fixture/worker", "version": "1.0.0"}) + "\n",
        encoding="utf-8",
    )
    (repo / "package-lock.json").write_text(
        json.dumps(
            {
                "name": "trusted-base",
                "lockfileVersion": 3,
                "packages": {
                    "": {"name": "trusted-base", "workspaces": ["packages/*"]},
                    "packages/worker": {
                        "name": "@fixture/worker",
                        "version": "1.0.0",
                    },
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    git(repo, "add", ".")
    git(repo, "commit", "-m", "npm base")
    base_sha = git(repo, "rev-parse", "HEAD")

    (repo / "package.json").write_text(
        json.dumps({"name": "untrusted-head", "private": True}) + "\n",
        encoding="utf-8",
    )
    (workspace / "package.json").write_text(
        json.dumps({"name": "@fixture/head", "version": "9.0.0"}) + "\n",
        encoding="utf-8",
    )
    (repo / "package-lock.json").write_text(
        json.dumps(
            {
                "name": "untrusted-head",
                "lockfileVersion": 3,
                "packages": {"": {"name": "untrusted-head"}},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    git(repo, "add", ".")
    git(repo, "commit", "-m", "npm head")
    return repo, base_sha


def test_materializes_only_exact_base_pnpm_inputs(tmp_path: Path) -> None:
    """PR-modified package metadata cannot enter the networked build context."""
    repo, base_sha = fixture_repo(tmp_path)
    output = tmp_path / "output"

    manifest = materializer.materialize(repo, base_sha, output)

    assert manifest == [
        {
            "directory": "project-000",
            "lock_blob": git(repo, "rev-parse", f"{base_sha}:frontend/pnpm-lock.yaml"),
            "package_manager": "pnpm@11.5.3",
            "revision_sha": base_sha,
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


def test_workflow_accepts_versioned_pnpm_materializer_manifest_record(
    tmp_path: Path,
) -> None:
    """The workflow predicate must accept the exact pnpm spec materialize emits."""
    repo, revision_sha = fixture_repo(tmp_path)
    manifest = materializer.materialize(repo, revision_sha, tmp_path / "output")
    record = manifest[0]
    assert record["package_manager"] == "pnpm@11.5.3"

    workflow = Path(".github/workflows/opencode-review-dispatch.yml").read_text(
        encoding="utf-8"
    )
    start = workflow.index("trusted_manifest_records_lock_revision() {")
    end = workflow.index("\n          }", start)
    predicate_line = next(
        line.strip()
        for line in workflow[start:end].splitlines()
        if line.strip().startswith("'any(.[];")
    )
    predicate = predicate_line.split("' \\", 1)[0][1:]
    command = [
        "jq",
        "-e",
        "--arg",
        "source",
        record["source"],
        "--arg",
        "manager",
        "pnpm",
        "--arg",
        "revision",
        record["revision_sha"],
        "--arg",
        "blob",
        record["lock_blob"],
        predicate,
    ]
    accepted = subprocess.run(
        command,
        input=json.dumps(manifest),
        capture_output=True,
        text=True,
        check=False,
    )
    assert accepted.returncode == 0, accepted.stderr

    wrong_manager = [{**record, "package_manager": "npm"}]
    rejected = subprocess.run(
        command,
        input=json.dumps(wrong_manager),
        capture_output=True,
        text=True,
        check=False,
    )
    assert rejected.returncode == 1, rejected.stderr


def test_materializes_only_exact_base_npm_inputs(tmp_path: Path) -> None:
    """PR-modified npm metadata cannot enter the networked build context."""
    repo, base_sha = npm_fixture_repo(tmp_path)
    output = tmp_path / "output"

    manifest = materializer.materialize(repo, base_sha, output)

    assert manifest == [
        {
            "directory": "project-000",
            "lock_blob": git(repo, "rev-parse", f"{base_sha}:package-lock.json"),
            "package_manager": "npm",
            "revision_sha": base_sha,
            "source": "package-lock.json",
        }
    ]
    assert (
        json.loads(
            (output / "project-000" / "package.json").read_text(encoding="utf-8")
        )["name"]
        == "trusted-base"
    )
    assert (
        json.loads(
            (output / "project-000" / "package-lock.json").read_text(encoding="utf-8")
        )["name"]
        == "trusted-base"
    )
    assert (
        json.loads(
            (output / "project-000" / "packages" / "worker" / "package.json").read_text(
                encoding="utf-8"
            )
        )["name"]
        == "@fixture/worker"
    )
    assert "untrusted-head" not in (
        output / "project-000" / "package-lock.json"
    ).read_text(encoding="utf-8")


def test_materializes_head_npm_manifest_when_lock_is_unchanged(tmp_path: Path) -> None:
    """An npm version change must prime Corepack even with the same lock blob."""
    repo, base_sha = npm_fixture_repo(tmp_path)
    git(
        repo,
        "checkout",
        base_sha,
        "--",
        "package.json",
        "package-lock.json",
        "packages/worker/package.json",
    )
    package_path = repo / "package.json"
    package_data = json.loads(package_path.read_text(encoding="utf-8"))
    package_data["packageManager"] = "npm@10.9.9"
    package_path.write_text(json.dumps(package_data) + "\n", encoding="utf-8")
    git(repo, "add", "package.json", "package-lock.json", "packages/worker/package.json")
    git(repo, "commit", "-m", "pin head npm")
    head_sha = git(repo, "rev-parse", "HEAD")

    manifest = materializer.materialize(
        repo, base_sha, tmp_path / "output", head_sha=head_sha
    )

    assert {entry["revision_sha"] for entry in manifest} == {base_sha, head_sha}
    head_entry = next(entry for entry in manifest if entry["revision_sha"] == head_sha)
    assert head_entry["lock_blob"] == git(
        repo, "rev-parse", f"{base_sha}:package-lock.json"
    )
    assert json.loads(
        (tmp_path / "output" / head_entry["directory"] / "package.json").read_text(
            encoding="utf-8"
        )
    )["packageManager"] == "npm@10.9.9"


def test_manifest_change_does_not_revalidate_unchanged_base_npm_lock(
    tmp_path: Path,
) -> None:
    """A legacy base lock stays trusted when only the head manifest changes."""
    repo, base_sha = npm_fixture_repo(tmp_path)
    git(
        repo,
        "checkout",
        base_sha,
        "--",
        "package.json",
        "package-lock.json",
        "packages/worker/package.json",
    )
    lock_path = repo / "package-lock.json"
    lock_path.write_text(
        json.dumps({"name": "trusted-base", "lockfileVersion": 1}) + "\n",
        encoding="utf-8",
    )
    git(repo, "add", "package-lock.json")
    git(repo, "commit", "-m", "retain legacy npm lock")
    legacy_base_sha = git(repo, "rev-parse", "HEAD")

    package_path = repo / "package.json"
    package_data = json.loads(package_path.read_text(encoding="utf-8"))
    package_data["packageManager"] = "npm@10.9.9"
    package_path.write_text(json.dumps(package_data) + "\n", encoding="utf-8")
    git(repo, "add", "package.json")
    git(repo, "commit", "-m", "pin head npm with legacy lock")
    head_sha = git(repo, "rev-parse", "HEAD")

    manifest = materializer.materialize(
        repo, legacy_base_sha, tmp_path / "output", head_sha=head_sha
    )

    assert {entry["revision_sha"] for entry in manifest} == {
        legacy_base_sha,
        head_sha,
    }


def test_npm_shrinkwrap_takes_precedence_over_package_lock(tmp_path: Path) -> None:
    """npm-shrinkwrap is materialized once with npm's documented precedence."""
    repo, _base_sha = npm_fixture_repo(tmp_path)
    (repo / "npm-shrinkwrap.json").write_text(
        json.dumps({"name": "shrinkwrapped", "lockfileVersion": 3, "packages": {}})
        + "\n",
        encoding="utf-8",
    )
    git(repo, "add", "npm-shrinkwrap.json")
    git(repo, "commit", "-m", "add shrinkwrap")
    base_sha = git(repo, "rev-parse", "HEAD")

    projects = materializer.base_npm_projects(repo, base_sha)

    assert len(projects) == 1
    assert projects[0][0] == "npm-shrinkwrap.json"
    assert "npm-shrinkwrap.json" in projects[0][2]
    assert "package-lock.json" not in projects[0][2]


def test_materializes_strict_changed_head_npm_lock_after_base(
    tmp_path: Path,
) -> None:
    """A bounded exact-head npm lock is cached alongside the trusted base."""
    repo, base_sha = npm_fixture_repo(tmp_path)
    head_package = {
        "name": "head",
        "version": "1.0.0",
        "resolved": "https://registry.npmjs.org/head/-/head-1.0.0.tgz",
        "integrity": "sha512-" + ("A" * 86) + "==",
    }
    (repo / "package-lock.json").write_text(
        json.dumps(
            {
                "name": "untrusted-head",
                "lockfileVersion": 3,
                "packages": {
                    "": {"name": "untrusted-head"},
                    "packages/worker": {
                        "name": "@fixture/worker",
                        "version": "1.0.0",
                    },
                    "node_modules/head": head_package,
                    "node_modules/worker": {
                        "resolved": "packages/worker",
                        "link": True,
                    },
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    git(repo, "add", "package-lock.json")
    git(repo, "commit", "-m", "bounded npm head")
    head_sha = git(repo, "rev-parse", "HEAD")
    output = tmp_path / "output"

    manifest = materializer.materialize(repo, base_sha, output, head_sha=head_sha)

    assert {entry["revision_sha"] for entry in manifest} == {base_sha, head_sha}
    assert [entry["source"] for entry in manifest] == ["package-lock.json"] * 2
    head_entry = next(entry for entry in manifest if entry["revision_sha"] == head_sha)
    assert head_entry["lock_blob"] == git(
        repo, "rev-parse", f"{head_sha}:package-lock.json"
    )
    assert (
        json.loads(
            (output / head_entry["directory"] / "package-lock.json").read_text(
                encoding="utf-8"
            )
        )["packages"]["node_modules/head"]
        == head_package
    )


def test_unchanged_head_npm_lock_is_not_materialized_twice(tmp_path: Path) -> None:
    """An unchanged exact lock reuses the base cache and manifest entry."""
    repo, base_sha = npm_fixture_repo(tmp_path)

    manifest = materializer.materialize(
        repo,
        base_sha,
        tmp_path / "output",
        head_sha=base_sha,
    )

    assert len(manifest) == 1
    assert manifest[0]["revision_sha"] == base_sha


def test_rejects_invalid_head_sha_during_materialization(tmp_path: Path) -> None:
    """A symbolic or abbreviated head cannot enter the networked context."""
    repo, base_sha = npm_fixture_repo(tmp_path)

    with pytest.raises(ValueError, match="head SHA must be exactly 40"):
        materializer.materialize(
            repo,
            base_sha,
            tmp_path / "output",
            head_sha="HEAD",
        )


def test_rejects_invalid_lock_blob_sha(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Manifest provenance must contain a full Git blob SHA."""
    monkeypatch.setattr(materializer, "_git", lambda *_args: b"not-a-sha\n")

    with pytest.raises(RuntimeError, match="invalid blob SHA"):
        materializer._lock_blob_sha(tmp_path, "a" * 40, "package-lock.json")


@pytest.mark.parametrize(
    ("lock_content", "message"),
    [
        (b"not-json", "invalid JSON"),
        (b"[]", "must be a JSON object"),
    ],
)
def test_rejects_malformed_changed_head_npm_lock_bytes(
    lock_content: bytes,
    message: str,
) -> None:
    """Changed HEAD locks must decode to a JSON object."""
    with pytest.raises(ValueError, match=message):
        materializer.validate_head_npm_lock("package-lock.json", lock_content)


@pytest.mark.parametrize(
    ("lock_data", "message"),
    [
        (
            {"lockfileVersion": 1, "packages": {}},
            "lockfileVersion 2 or 3",
        ),
        (
            {"lockfileVersion": 3, "packages": []},
            "object-valued packages map",
        ),
        (
            {
                "lockfileVersion": 3,
                "packages": {"node_modules/pkg": []},
            },
            "malformed package metadata",
        ),
        (
            {
                "lockfileVersion": 3,
                "packages": {"..\\escape": {}},
            },
            "unsafe package path",
        ),
        (
            {
                "lockfileVersion": 3,
                "packages": {"../escape": {}},
            },
            "unsafe package path",
        ),
        (
            {
                "lockfileVersion": 3,
                "packages": {
                    "node_modules/pkg": {
                        "resolved": "https://example.invalid/pkg.tgz",
                        "integrity": "sha512-" + ("A" * 86) + "==",
                    }
                },
            },
            "must resolve from https://registry.npmjs.org/",
        ),
        (
            {
                "lockfileVersion": 3,
                "packages": {
                    "node_modules/pkg": {
                        "resolved": "https://registry.npmjs.org/pkg/-/pkg-1.0.0.tgz",
                        "integrity": "sha256-unsafe",
                    }
                },
            },
            "one SHA-512 integrity",
        ),
        (
            {
                "lockfileVersion": 3,
                "packages": {
                    "node_modules/workspace": {
                        "link": True,
                    }
                },
            },
            "unsafe workspace link",
        ),
        (
            {
                "lockfileVersion": 3,
                "packages": {
                    "node_modules/workspace": {
                        "resolved": "../escape",
                        "link": True,
                    }
                },
            },
            "unsafe workspace link",
        ),
        (
            {
                "lockfileVersion": 3,
                "packages": {"node_modules/pkg": {}},
            },
            "must pin a registry tarball and SHA-512 integrity",
        ),
        (
            {
                "lockfileVersion": 3,
                "packages": {
                    "node_modules/pkg": {
                        "resolved": "https://registry.npmjs.org:bad/pkg/-/pkg-1.0.0.tgz",
                        "integrity": "sha512-" + ("A" * 86) + "==",
                    }
                },
            },
            "invalid registry URL",
        ),
    ],
)
def test_rejects_unbounded_changed_head_npm_lock(
    lock_data: dict[str, object],
    message: str,
) -> None:
    """Changed HEAD locks cannot introduce registry, path, or hash ambiguity."""
    with pytest.raises(ValueError, match=message):
        materializer.validate_head_npm_lock(
            "package-lock.json",
            (json.dumps(lock_data) + "\n").encode(),
        )


def test_skips_npm_lock_when_exact_pnpm_declaration_owns_project(
    tmp_path: Path,
) -> None:
    """A vestigial npm lock cannot duplicate an exact pnpm project."""
    repo, base_sha = fixture_repo(tmp_path)
    git(repo, "checkout", base_sha)
    (repo / "frontend" / "package-lock.json").write_text(
        '{"lockfileVersion":3,"packages":{}}\n', encoding="utf-8"
    )
    git(repo, "add", "frontend/package-lock.json")
    git(repo, "commit", "-m", "add vestigial npm lock")
    current_sha = git(repo, "rev-parse", "HEAD")

    assert materializer.base_npm_projects(repo, current_sha) == []
    assert len(materializer.base_pnpm_projects(repo, current_sha)) == 1


def test_rejects_invalid_base_sha(tmp_path: Path) -> None:
    """Git options and symbolic refs cannot cross the exact-SHA boundary."""
    with pytest.raises(ValueError, match="40 hexadecimal"):
        materializer.base_pnpm_projects(tmp_path, "--help")
    with pytest.raises(ValueError, match="40 hexadecimal"):
        materializer.base_npm_projects(tmp_path, "--help")


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

    with pytest.raises(ValueError, match=r"no regular sibling package\.json"):
        materializer.base_pnpm_projects(repo, git(repo, "rev-parse", "HEAD"))


def test_rejects_npm_lock_without_sibling_package_manifest(tmp_path: Path) -> None:
    """An npm lock without its exact base package manifest fails closed."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "user.name", "Test")
    git(repo, "config", "user.email", "test@example.invalid")
    (repo / "package-lock.json").write_text(
        '{"lockfileVersion":3,"packages":{}}\n', encoding="utf-8"
    )
    git(repo, "add", ".")
    git(repo, "commit", "-m", "base")

    with pytest.raises(ValueError, match=r"no regular sibling package\.json"):
        materializer.base_npm_projects(repo, git(repo, "rev-parse", "HEAD"))


@pytest.mark.parametrize(
    ("package_content", "lock_content", "message"),
    [
        (b"not-json", b'{"lockfileVersion":3}', "invalid JSON"),
        (b"[]", b'{"lockfileVersion":3}', "must be a JSON object"),
        (b"{}", b"\n", "npm lock frontend/package-lock.json is empty"),
        (b"{}", b"not-json", "invalid JSON"),
        (b"{}", b"[]", "must be a JSON object"),
    ],
)
def test_rejects_invalid_base_npm_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    package_content: bytes,
    lock_content: bytes,
    message: str,
) -> None:
    """Malformed exact-base npm manifests and locks fail before use."""
    regular_paths = {"frontend/package.json", "frontend/package-lock.json"}
    monkeypatch.setattr(
        materializer,
        "_regular_base_paths",
        lambda *_args: regular_paths,
    )

    def fake_git(_repo_root: Path, _command: str, object_spec: str) -> bytes:
        if object_spec.endswith(":frontend/package.json"):
            return package_content
        if object_spec.endswith(":frontend/package-lock.json"):
            return lock_content
        raise AssertionError(f"unexpected git object: {object_spec}")

    monkeypatch.setattr(materializer, "_git", fake_git)
    with pytest.raises(ValueError, match=message):
        materializer.base_npm_projects(tmp_path, "a" * 40)


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


@pytest.mark.parametrize("npm_lock_name", materializer.NPM_LOCK_NAMES)
def test_skips_npm_project_with_vestigial_pnpm_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    npm_lock_name: str,
) -> None:
    """An npm project's stray pnpm-lock.yaml is skipped, not fail-closed.

    A base tree with a ``pnpm-lock.yaml`` plus any sibling npm lock and no exact
    pnpm ``packageManager`` is npm-managed, so pnpm materialization is skipped
    (the downstream npm install path owns it) rather than failing the whole
    coverage-evidence job.
    """
    regular_paths = {
        "frontend/package.json",
        "frontend/pnpm-lock.yaml",
        f"frontend/{npm_lock_name}",
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
        lambda *_args, **_kwargs: [
            {
                "directory": "project-000",
                "lock_blob": "b" * 40,
                "package_manager": "pnpm@11.5.3",
                "revision_sha": "a" * 40,
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
        "Materialized trusted JavaScript lock frontend/pnpm-lock.yaml "
        f"for pnpm@11.5.3 from {'a' * 40} as project-000/pnpm-lock.yaml."
        in capsys.readouterr().out
    )


def test_main_escapes_pull_request_paths_in_github_logs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A malicious repository path cannot emit a second Actions command."""
    malicious_source = "::set-output name=leak::value\nfrontend/package-lock.json"
    monkeypatch.setattr(
        materializer,
        "materialize",
        lambda *_args, **_kwargs: [
            {
                "directory": "project-000",
                "lock_blob": "b" * 40,
                "package_manager": "npm",
                "revision_sha": "a" * 40,
                "source": malicious_source,
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

    output = capsys.readouterr().out
    assert "\n::set-output" not in output
    assert (
        "%3A%3Aset-output name=leak%3A%3Avalue%0Afrontend/package-lock.json"
        in output
    )


def test_main_reports_empty_base(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The CLI distinguishes an empty trusted base from extraction failure."""
    monkeypatch.setattr(materializer, "materialize", lambda *_args, **_kwargs: [])
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
        "No tracked supported JavaScript package lockfiles exist"
        in capsys.readouterr().out
    )


def test_main_preserves_failure_reason(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Materialization failures remain diagnosable and fail closed."""

    def fail_materialize(
        _repo_root: Path,
        _base_sha: str,
        _output_dir: Path,
        **_kwargs: object,
    ) -> None:
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


def _bounded_head_pnpm_lock() -> str:
    """Return a realistic registry- and integrity-bounded pnpm lockfile body."""
    return (
        "lockfileVersion: '9.0'\n"
        "\n"
        "settings:\n"
        "  autoInstallPeers: true\n"
        "\n"
        "packages:\n"
        "  fast-uri@3.1.5:\n"
        "    resolution: {integrity: sha512-" + ("B" * 86) + "==}\n"
        "\n"
        "snapshots:\n"
        "  fast-uri@3.1.5: {}\n"
    )


def pnpm_head_fixture_repo(tmp_path: Path) -> tuple[Path, str]:
    """Create a pnpm repository whose head raises a dependency floor."""
    repo = tmp_path / "pnpm-head-repo"
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
        "packages:\n"
        "  fast-uri@3.1.4:\n"
        "    resolution: {integrity: sha512-" + ("A" * 86) + "==}\n"
        "\n"
        "snapshots:\n"
        "  fast-uri@3.1.4: {}\n",
        encoding="utf-8",
    )
    git(repo, "add", ".")
    git(repo, "commit", "-m", "pnpm base")
    base_sha = git(repo, "rev-parse", "HEAD")

    (repo / "frontend" / "package.json").write_text(
        json.dumps({"packageManager": "pnpm@11.5.3"}) + "\n",
        encoding="utf-8",
    )
    (repo / "frontend" / "pnpm-lock.yaml").write_text(
        _bounded_head_pnpm_lock(),
        encoding="utf-8",
    )
    git(repo, "add", ".")
    git(repo, "commit", "-m", "pnpm bounded head")
    return repo, base_sha


def test_materializes_strict_changed_head_pnpm_lock_after_base(
    tmp_path: Path,
) -> None:
    """A registry- and hash-bounded head pnpm lock joins the trusted store."""
    repo, base_sha = pnpm_head_fixture_repo(tmp_path)
    head_sha = git(repo, "rev-parse", "HEAD")
    output = tmp_path / "output"

    manifest = materializer.materialize(repo, base_sha, output, head_sha=head_sha)

    assert {entry["revision_sha"] for entry in manifest} == {base_sha, head_sha}
    head_entry = next(
        entry
        for entry in manifest
        if entry["revision_sha"] == head_sha and entry["source"] == "frontend/pnpm-lock.yaml"
    )
    assert head_entry["lock_blob"] == git(
        repo, "rev-parse", f"{head_sha}:frontend/pnpm-lock.yaml"
    )
    assert (
        output / head_entry["directory"] / "pnpm-lock.yaml"
    ).read_text(encoding="utf-8") == _bounded_head_pnpm_lock()


def test_unchanged_head_pnpm_lock_is_not_materialized_twice(
    tmp_path: Path,
) -> None:
    """An unchanged head pnpm lock reuses the exact base cache entry."""
    repo, base_sha = pnpm_head_fixture_repo(tmp_path)

    manifest = materializer.materialize(
        repo,
        base_sha,
        tmp_path / "output",
        head_sha=base_sha,
    )

    assert len(manifest) == 1
    assert manifest[0]["revision_sha"] == base_sha


def test_rejects_malformed_changed_head_pnpm_lock(tmp_path: Path) -> None:
    """A head pnpm lock without an integrity pin cannot enter the store."""
    repo, base_sha = pnpm_head_fixture_repo(tmp_path)
    (repo / "frontend" / "pnpm-lock.yaml").write_text(
        "lockfileVersion: '9.0'\npackages:\n  hostile@9.9.9: {}\n",
        encoding="utf-8",
    )
    git(repo, "add", ".")
    git(repo, "commit", "-m", "hostile pnpm head")
    head_sha = git(repo, "rev-parse", "HEAD")

    with pytest.raises(ValueError, match="has no resolution entry"):
        materializer.materialize(repo, base_sha, tmp_path / "output", head_sha=head_sha)


def test_rejects_off_registry_tarball_in_changed_head_pnpm_lock(
    tmp_path: Path,
) -> None:
    """A non-npmjs tarball source is refused before image build."""
    repo, base_sha = pnpm_head_fixture_repo(tmp_path)
    (repo / "frontend" / "pnpm-lock.yaml").write_text(
        "lockfileVersion: '9.0'\n"
        "packages:\n"
        "  evil@1.0.0:\n"
        "    resolution: {tarball: https://evil.invalid/evil/-/evil-1.0.0.tgz,"
        " integrity: sha512-" + ("C" * 86) + "==}\n",
        encoding="utf-8",
    )
    git(repo, "add", ".")
    git(repo, "commit", "-m", "off-registry tarball head")
    head_sha = git(repo, "rev-parse", "HEAD")

    with pytest.raises(ValueError, match="must resolve from https"):
        materializer.materialize(repo, base_sha, tmp_path / "output", head_sha=head_sha)


def test_rejects_unsafe_workspace_link_in_changed_head_pnpm_lock(
    tmp_path: Path,
) -> None:
    """Workspace links must stay inside the project tree."""
    repo, base_sha = pnpm_head_fixture_repo(tmp_path)
    (repo / "frontend" / "pnpm-lock.yaml").write_text(
        "lockfileVersion: '9.0'\n"
        "packages:\n"
        "  escape@1.0.0:\n"
        "    resolution: {directory: ../../secrets, link: true}\n",
        encoding="utf-8",
    )
    git(repo, "add", ".")
    git(repo, "commit", "-m", "escaping workspace link head")
    head_sha = git(repo, "rev-parse", "HEAD")

    with pytest.raises(ValueError, match="unsafe directory target"):
        materializer.materialize(repo, base_sha, tmp_path / "output", head_sha=head_sha)


def test_validate_head_pnpm_lock_accepts_bounded_lock() -> None:
    """The validator accepts exactly the lock shape the store can prefetch."""
    materializer.validate_head_pnpm_lock(
        "pnpm-lock.yaml", _bounded_head_pnpm_lock().encode("utf-8")
    )


def test_validate_head_pnpm_lock_accepts_multi_key_resolution_mappings() -> None:
    """Comma-delimited inline values must retain exact token boundaries."""
    integrity = "sha512-" + ("E" * 86) + "=="
    tarball = "https://registry.npmjs.org/example/-/example-1.0.0.tgz"
    for resolution in (
        f"tarball: {tarball}, integrity: {integrity}",
        f"integrity: {integrity}, tarball: {tarball}",
    ):
        content = (
            "lockfileVersion: '9.0'\n"
            "packages:\n"
            "  example@1.0.0:\n"
            f"    resolution: {{{resolution}}}\n"
        )
        materializer.validate_head_pnpm_lock(
            "pnpm-lock.yaml", content.encode("utf-8")
        )


def test_validate_head_pnpm_lock_accepts_fetch_words_in_deprecation_text() -> None:
    """Metadata prose cannot be reclassified as an artifact source declaration."""
    integrity = "sha512-" + ("F" * 86) + "=="
    content = (
        "lockfileVersion: '9.0'\n"
        "packages:\n"
        "  example@1.0.0:\n"
        f"    resolution: {{integrity: {integrity}}}\n"
        "    deprecated: migrate from git+https://example.invalid/source; "
        "the tarball: note is informational only\n"
    )
    materializer.validate_head_pnpm_lock(
        "pnpm-lock.yaml", content.encode("utf-8")
    )


@pytest.mark.parametrize(
    ("directory", "accepted"),
    (
        ("packages/example", True),
        ("/tmp/example", False),
        ("../example", False),
        ("node_modules/example", False),
    ),
)
def test_validate_head_pnpm_lock_bounds_workspace_directory_variants(
    directory: str, accepted: bool
) -> None:
    """Workspace targets are admitted only when they remain project-relative."""
    content = (
        "lockfileVersion: '9.0'\n"
        "packages:\n"
        "  workspace@example:\n"
        f"    resolution: {{directory: {directory}, link: true}}\n"
    ).encode("utf-8")

    if accepted:
        materializer.validate_head_pnpm_lock("pnpm-lock.yaml", content)
    else:
        with pytest.raises(ValueError, match="unsafe directory target"):
            materializer.validate_head_pnpm_lock("pnpm-lock.yaml", content)


@pytest.mark.parametrize(
    ("content", "message"),
    (
        (b"\xff", "invalid UTF-8"),
        (b"lockfileVersion: '9.0'\npackages:\n  : malformed\n", "unexpected two-space entry"),
        (
            b"lockfileVersion: '9.0'\npackages:\n  first@1.0.0:\n  second@1.0.0:\n",
            "first@1.0.0 has no resolution entry",
        ),
        (
            b"lockfileVersion: '9.0'\npackages:\n  malformed@1.0.0:\n    resolution:\n",
            "multi-line or malformed resolution mapping",
        ),
        (
            b"lockfileVersion: '9.0'\npackages:\n  workspace@example:\n    resolution: {link: true}\n",
            "must carry a relative directory target",
        ),
        (
            b"lockfileVersion: '9.0'\npackages:\n  weak@1.0.0:\n    resolution: {integrity: sha256-weak}\n",
            "must pin exactly one SHA-512 integrity value",
        ),
        (
            b"lockfileVersion: '9.0'\npackages:\n  tarball@1.0.0:\n    tarball: https://registry.npmjs.org/tarball/-/tarball-1.0.0.tgz\n",
            "carries an out-of-band fetch source",
        ),
        (
            b"lockfileVersion: '9.0'\npackages:\n  git@1.0.0:\n    git+https://example.invalid/git.git\n",
            "carries an out-of-band fetch source",
        ),
        (b"lockfileVersion: '9.0'\npackages:\n", "contains no package entries"),
    ),
)
def test_validate_head_pnpm_lock_rejects_malformed_structures(
    content: bytes, message: str
) -> None:
    """Every structural fail-closed path remains executable evidence."""
    with pytest.raises(ValueError, match=message):
        materializer.validate_head_pnpm_lock("pnpm-lock.yaml", content)


def test_validate_head_pnpm_lock_rejects_invalid_tarball_port() -> None:
    """A non-numeric registry port cannot escape URL validation as metadata."""
    integrity = "sha512-" + ("G" * 86) + "=="
    content = (
        "lockfileVersion: '9.0'\n"
        "packages:\n"
        "  invalid-port@1.0.0:\n"
        "    resolution: {tarball: "
        "https://registry.npmjs.org:not-a-port/invalid-port/-/invalid-port-1.0.0.tgz, "
        f"integrity: {integrity}}}\n"
    )
    with pytest.raises(ValueError, match="invalid tarball URL"):
        materializer.validate_head_pnpm_lock(
            "pnpm-lock.yaml", content.encode("utf-8")
        )


def test_validate_head_pnpm_lock_rejects_empty_and_git_sources() -> None:
    """Empty locks and VCS fetch sources fail closed."""
    with pytest.raises(ValueError, match="empty"):
        materializer.validate_head_pnpm_lock("pnpm-lock.yaml", b"")
    with pytest.raises(ValueError, match="must resolve from https"):
        content = (
            "lockfileVersion: '9.0'\n"
            "packages:\n"
            "  gitdep@1.0.0:\n"
            "    resolution: {tarball: https://codeload.github.com/example/example/tar.gz/abc123,"
            " integrity: sha512-" + ("D" * 86) + "==}\n"
            "    # git+https://example.invalid/example.git\n"
        )
        materializer.validate_head_pnpm_lock("pnpm-lock.yaml", content.encode("utf-8"))
