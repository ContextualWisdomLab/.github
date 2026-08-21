"""Tests for exact-base Rust toolchain materialization."""

from __future__ import annotations

import json
import runpy
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.ci import materialize_base_rust_toolchain as materializer


def git(repo: Path, *args: str) -> str:
    """Run Git in one temporary fixture repository."""
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def init_repo(tmp_path: Path, name: str = "repo") -> Path:
    """Create an empty Git repository with a deterministic test identity."""
    repo = tmp_path / name
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "user.name", "Test")
    git(repo, "config", "user.email", "test@example.invalid")
    return repo


def commit(repo: Path, message: str = "fixture") -> str:
    """Commit the fixture tree and return its exact revision."""
    git(repo, "add", "-A")
    git(repo, "commit", "--allow-empty", "-m", message)
    return git(repo, "rev-parse", "HEAD")


def rust_workspace(tmp_path: Path) -> tuple[Path, str]:
    """Create an OriginWeave-style workspace and return its base revision."""
    repo = init_repo(tmp_path)
    (repo / "Cargo.toml").write_text(
        "[workspace]\n"
        'members = ["crates/originweave-destination", "crates/originweave-core"]\n'
        'resolver = "3"\n\n'
        "[workspace.package]\n"
        'edition = "2024"\n'
        'rust-version = "1.97"\n',
        encoding="utf-8",
    )
    (repo / "Cargo.lock").write_text("# lock\n", encoding="utf-8")
    (repo / "rust-toolchain.toml").write_text(
        '[toolchain]\nchannel = "1.97.1"\n',
        encoding="utf-8",
    )
    destination = repo / "crates/originweave-destination"
    destination.mkdir(parents=True)
    (destination / "Cargo.toml").write_text(
        '[package]\nname = "originweave-destination"\nversion = "0.1.0"\n',
        encoding="utf-8",
    )
    (destination / "src").mkdir()
    (destination / "src/lib.rs").write_text("pub fn ok() {}\n", encoding="utf-8")
    core = repo / "crates/originweave-core"
    core.mkdir(parents=True)
    (core / "Cargo.toml").write_text(
        '[package]\nname = "originweave-core"\nversion = "0.1.0"\n',
        encoding="utf-8",
    )
    return repo, commit(repo, "workspace")


def test_materialize_reads_rust_inputs_from_exact_base_commit(tmp_path: Path) -> None:
    """A pull request cannot select the trusted base Rust toolchain or lock."""
    repo, base_sha = rust_workspace(tmp_path)
    (repo / "rust-toolchain.toml").write_text(
        '[toolchain]\nchannel = "1.99.0"\n',
        encoding="utf-8",
    )
    (repo / "Cargo.lock").write_text("# pull-request lock\n", encoding="utf-8")
    commit(repo, "untrusted pull-request inputs")

    output = tmp_path / "base-rust"
    assert materializer.main(
        [
            "--repo-root",
            str(repo),
            "--base-sha",
            base_sha,
            "--output-dir",
            str(output),
        ]
    ) == 0

    payload = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert payload["revision_sha"] == base_sha
    assert payload["rustup_channel"] == "1.97.1"
    assert (output / "Cargo.lock").read_text(encoding="utf-8") == "# lock\n"


def test_originweave_workspace_copies_only_base_rust_metadata(tmp_path: Path) -> None:
    """Only tracked base manifests, lock, and toolchain metadata enter the image."""
    repo, base_sha = rust_workspace(tmp_path)
    output = tmp_path / "base-rust"
    payload = materializer.materialize(repo, base_sha, output)
    assert payload == {
        "revision_sha": base_sha,
        "rustup_channel": "1.97.1",
        "has_lock": True,
        "has_manifest": True,
        "inputs": [
            "rust-toolchain.toml",
            "Cargo.toml",
            "Cargo.lock",
            "crates/originweave-destination/Cargo.toml",
            "crates/originweave-core/Cargo.toml",
        ],
    }
    assert (output / "crates/originweave-destination/Cargo.toml").is_file()
    assert not (output / "crates/originweave-destination/src/lib.rs").exists()


@pytest.mark.parametrize(
    ("rust_version", "expected"),
    [("1.97", "1.97"), ("1.85.0", None), ("1.80", None), ("stable", None)],
)
def test_rust_version_selects_only_newer_numeric_toolchains(
    tmp_path: Path, rust_version: str, expected: str | None
) -> None:
    """Only a numeric rust-version newer than Debian rustc selects rustup."""
    repo = init_repo(tmp_path)
    (repo / "Cargo.toml").write_text(
        f'[package]\nname = "fixture"\nversion = "0.1.0"\nrust-version = "{rust_version}"\n',
        encoding="utf-8",
    )
    revision = commit(repo)
    assert materializer.declared_rust_version(repo, revision) == rust_version
    assert materializer.rustup_channel(repo, revision) == expected


def test_legacy_toolchain_file_selects_a_safe_channel(tmp_path: Path) -> None:
    """A base-owned legacy rust-toolchain file can select a bounded channel."""
    repo = init_repo(tmp_path)
    (repo / "Cargo.toml").write_text('[package]\nname = "x"\nversion = "0.1.0"\n')
    (repo / "rust-toolchain").write_text("nightly-2026-08-01\n")
    revision = commit(repo)
    assert materializer.toolchain_channel(repo, revision) == "nightly-2026-08-01"
    assert materializer.rustup_channel(repo, revision) == "nightly-2026-08-01"


def test_tree_without_cargo_manifest_writes_empty_revision_manifest(tmp_path: Path) -> None:
    """A non-Rust base commit records its revision without installing Rust."""
    repo = init_repo(tmp_path)
    revision = commit(repo)
    payload = materializer.materialize(repo, revision, tmp_path / "out")
    assert payload["revision_sha"] == revision
    assert payload["rustup_channel"] is None
    assert payload["has_manifest"] is False
    assert payload["inputs"] == []


def test_workspace_member_path_and_glob_validation_fail_closed(tmp_path: Path) -> None:
    """Traversal, recursive globs, and in-segment globs cannot select blobs."""
    repo = init_repo(tmp_path)
    (repo / "Cargo.toml").write_text('[workspace]\nmembers = ["../escape"]\n')
    revision = commit(repo, "traversal")
    with pytest.raises(ValueError, match="bounded repository path"):
        materializer.workspace_member_manifests(repo, revision)
    for member in ("crates/**", "cr*tes/foo", "crates/?"):
        with pytest.raises(ValueError, match="unsupported workspace member glob"):
            materializer.expand_workspace_member(member, {"Cargo.toml"})


def test_symlink_inputs_do_not_cross_the_regular_blob_boundary(tmp_path: Path) -> None:
    """Git symlink entries are excluded instead of following worktree targets."""
    repo, _ = rust_workspace(tmp_path)
    outside = tmp_path / "outside.lock"
    outside.write_text("outside\n")
    (repo / "Cargo.lock").unlink()
    (repo / "Cargo.lock").symlink_to(outside)
    revision = commit(repo, "symlink lock")
    output = tmp_path / "out"
    payload = materializer.materialize(repo, revision, output)
    assert payload["has_lock"] is False
    assert not (output / "Cargo.lock").exists()


def test_cli_and_script_entrypoint_require_exact_base_sha(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The workflow CLI and script entrypoint bind output to the given revision."""
    repo, revision = rust_workspace(tmp_path)
    output = tmp_path / "cli-out"
    argv = [
        "--repo-root",
        str(repo),
        "--base-sha",
        revision,
        "--output-dir",
        str(output),
    ]
    assert materializer.main(argv) == 0
    assert json.loads(capsys.readouterr().out)["revision_sha"] == revision
    monkeypatch.setattr(sys, "argv", [materializer.__file__, *argv[:-1], str(tmp_path / "entry")])
    with pytest.raises(SystemExit, match="0"):
        runpy.run_path(materializer.__file__, run_name="__main__")


def test_workspace_glob_expands_only_immediate_base_crates(tmp_path: Path) -> None:
    """A trailing glob includes immediate crate manifests but not deeper paths."""
    repo = init_repo(tmp_path)
    (repo / "Cargo.toml").write_text('[workspace]\nmembers = ["crates/*"]\n')
    direct = repo / "crates/direct"
    direct.mkdir(parents=True)
    (direct / "Cargo.toml").write_text('[package]\nname = "direct"\nversion = "0.1.0"\n')
    deep = repo / "crates/group/deep"
    deep.mkdir(parents=True)
    (deep / "Cargo.toml").write_text('[package]\nname = "deep"\nversion = "0.1.0"\n')
    revision = commit(repo)
    assert materializer.workspace_member_manifests(repo, revision) == [
        "crates/direct/Cargo.toml"
    ]


def test_non_list_and_missing_workspace_members_yield_no_manifests(tmp_path: Path) -> None:
    """Non-list metadata and absent member blobs cannot become Rust inputs."""
    repo = init_repo(tmp_path)
    (repo / "Cargo.toml").write_text('[workspace]\nmembers = "crates/*"\n')
    non_list = commit(repo, "non-list")
    assert materializer.workspace_member_manifests(repo, non_list) == []
    (repo / "Cargo.toml").write_text('[workspace]\nmembers = [1, "missing"]\n')
    missing = commit(repo, "missing")
    assert materializer.workspace_member_manifests(repo, missing) == []


def test_invalid_toml_and_unsafe_channels_fail_closed(tmp_path: Path) -> None:
    """Malformed metadata and unsafe toolchain channels never select rustup."""
    with pytest.raises(materializer.tomllib.TOMLDecodeError):
        materializer.read_toml(b"this is not toml [[[", "Cargo.toml")
    with (
        pytest.raises(TypeError, match="TOML table"),
        pytest.MonkeyPatch.context() as monkeypatch,
    ):
        monkeypatch.setattr(materializer.tomllib, "loads", lambda _text: ["not-table"])
        materializer.read_toml(b"ignored", "Cargo.toml")

    repo = init_repo(tmp_path)
    (repo / "Cargo.toml").write_text('[package]\nname = "x"\nversion = "0.1.0"\n')
    (repo / "rust-toolchain.toml").write_text('[toolchain]\nchannel = "../evil"\n')
    (repo / "rust-toolchain").write_text("not a channel!\n")
    revision = commit(repo)
    assert materializer.toolchain_channel(repo, revision) is None


def test_tracked_paths_accept_only_well_formed_regular_blobs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Tree parsing excludes symlinks and directories and validates every entry."""
    repo = tmp_path
    revision = "a" * 40
    blob = "b" * 40
    monkeypatch.setattr(
        materializer,
        "_git",
        lambda *_args: (
            f"100644 blob {blob}\tCargo.toml\0"
            f"100755 blob {blob}\tscripts/tool\0"
            f"120000 blob {blob}\tCargo.lock\0"
            f"040000 tree {blob}\tcrates\0"
        ).encode(),
    )
    assert materializer.tracked_paths(repo, revision) == {"Cargo.toml", "scripts/tool"}

    for malformed, match in (
        (b"broken\0", "malformed tree entry"),
        (b"100644 blob bad\tCargo.toml\0", "invalid object identity"),
        (f"100644 blob {blob}\t../escape\0".encode(), "bounded repository path"),
        (f"100644 blob {blob}\tbad-".encode() + b"\xff\0", "valid UTF-8"),
    ):
        monkeypatch.setattr(materializer, "_git", lambda *_args, value=malformed: value)
        with pytest.raises((RuntimeError, ValueError), match=match):
            materializer.tracked_paths(repo, revision)


def test_git_object_reader_rejects_untrusted_invocations_and_repositories(tmp_path: Path) -> None:
    """Only exact tree/blob reads execute, and invalid repository metadata fails closed."""
    repo = tmp_path / "repo"
    repo.mkdir()
    with pytest.raises(RuntimeError, match="unsupported invocation"):
        materializer._git(repo, "status")
    with pytest.raises(RuntimeError, match="unsupported invocation"):
        materializer._git(repo)
    with pytest.raises(ValueError, match="exactly 40"):
        materializer._git(repo, "ls-tree", "-rz", "--full-tree", "main")
    with pytest.raises(ValueError, match="blob selector"):
        materializer._git(repo, "show", "main:Cargo.toml")
    with pytest.raises(RuntimeError, match="not a git repository"):
        materializer.tracked_paths(repo, "a" * 40)

    git_path = repo / ".git"
    git_path.symlink_to(tmp_path)
    with pytest.raises(RuntimeError, match="symbolic link"):
        materializer.tracked_paths(repo, "a" * 40)
    git_path.unlink()
    git_path.write_text("not a pointer\n")
    with pytest.raises(RuntimeError, match="invalid gitdir pointer"):
        materializer.tracked_paths(repo, "a" * 40)
    git_path.write_text("gitdir: missing\n")
    with pytest.raises(RuntimeError, match="not a regular directory"):
        materializer.tracked_paths(repo, "a" * 40)


def test_real_git_failures_and_gitdir_pointers_are_handled(tmp_path: Path) -> None:
    """Missing objects fail closed while a regular worktree pointer remains readable."""
    repo, revision = rust_workspace(tmp_path)
    with pytest.raises(RuntimeError, match="git ls-tree failed"):
        materializer.tracked_paths(repo, "f" * 40)
    moved = tmp_path / "real-git"
    (repo / ".git").rename(moved)
    (repo / ".git").write_text(f"gitdir: {moved}\n")
    assert "Cargo.toml" in materializer.tracked_paths(repo, revision)


def test_invalid_sha_output_symlink_and_nonregular_blob_fail_closed(tmp_path: Path) -> None:
    """Revision, output, and regular-blob boundaries reject ambiguous inputs."""
    repo, revision = rust_workspace(tmp_path)
    with pytest.raises(ValueError, match="base SHA"):
        materializer.materialize(repo, "main", tmp_path / "out")
    linked_output = tmp_path / "linked-output"
    linked_output.symlink_to(tmp_path / "elsewhere")
    with pytest.raises(ValueError, match="output directory"):
        materializer.materialize(repo, revision, linked_output)
    with pytest.raises(ValueError, match="non-regular"):
        materializer._read_blob(repo, revision, "Cargo.lock", {"Cargo.toml"})


def test_existing_destination_symlink_and_invalid_base_toml_fail_cli(tmp_path: Path) -> None:
    """The materializer neither replaces output symlinks nor accepts malformed base TOML."""
    repo, revision = rust_workspace(tmp_path)
    output = tmp_path / "out"
    output.mkdir()
    (output / "Cargo.toml").symlink_to(tmp_path / "outside")
    with pytest.raises(ValueError, match="symlinked Rust output"):
        materializer.materialize(repo, revision, output)

    (repo / "Cargo.toml").write_text("this is not toml [[[\n")
    corrupt = commit(repo, "corrupt")
    with pytest.raises(SystemExit):
        materializer.main(
            [
                "--repo-root",
                str(repo),
                "--base-sha",
                corrupt,
                "--output-dir",
                str(tmp_path / "corrupt-out"),
            ]
        )


def test_parse_helpers_and_bounded_paths_cover_edge_cases() -> None:
    """Version and path helpers accept normalized values and reject ambiguity."""
    assert materializer.parse_rust_version("1.97") == (1, 97, 0)
    assert materializer.parse_rust_version("1.85.0") == (1, 85, 0)
    assert materializer.parse_rust_version("nightly") is None
    assert materializer._nested({}, "missing.value") is None
    assert materializer._nested({"value": "not-a-table"}, "value.child") is None
    assert materializer._bounded_member_path("crates/core").as_posix() == "crates/core"
    for path in ("", "/absolute", "./dot", "a/../b", "a\\b", "a//b"):
        with pytest.raises(ValueError, match="bounded repository path"):
            materializer._bounded_repo_path(path)


def test_absent_rust_metadata_and_empty_legacy_channel_take_no_toolchain_path(
    tmp_path: Path,
) -> None:
    """Absent version fields and an empty legacy file select no Rust toolchain."""
    repo = init_repo(tmp_path)
    empty = commit(repo, "empty")
    assert materializer.declared_rust_version(repo, empty) is None
    assert materializer.workspace_member_manifests(repo, empty) == []
    assert materializer.rustup_channel(repo, empty) is None
    with pytest.raises(ValueError, match="base SHA"):
        materializer.tracked_paths(repo, "main")

    (repo / "Cargo.toml").write_text('[package]\nname = "x"\nversion = "0.1.0"\n')
    (repo / "rust-toolchain").write_text("")
    no_version = commit(repo, "no version")
    assert materializer.declared_rust_version(repo, no_version) is None
    assert materializer.toolchain_channel(repo, no_version) is None
    assert materializer.rustup_channel(repo, no_version) is None
