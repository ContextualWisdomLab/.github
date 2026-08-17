"""Tests for bounded Rust toolchain materialization into the coverage image."""

from __future__ import annotations

import json
import runpy
import struct
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.ci import materialize_base_rust_toolchain as materializer


def _git_index(names: list[bytes], *, version: int = 2, extended: bool = False) -> bytes:
    """Build a minimal git index for parser tests."""
    entries = b""
    for name in names:
        flags = (0x0FFF if len(name) >= 0x0FFF else len(name)) | (0x4000 if extended else 0)
        header = b"\0" * 60 + struct.pack(">H", flags)
        if extended:
            header += b"\0\0"
        payload = header + name + b"\0"
        payload += b"\0" * ((8 - (len(payload) % 8)) % 8)
        entries += payload
    return b"DIRC" + struct.pack(">II", version, len(names)) + entries


def git(repo: Path, *args: str) -> str:
    """Run git in a temporary fixture repository."""
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def rust_workspace(tmp_path: Path) -> Path:
    """Create an OriginWeave-style virtual workspace with a pinned toolchain."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "user.name", "Test")
    git(repo, "config", "user.email", "test@example.invalid")
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
        "[package]\nname = \"originweave-destination\"\nversion = \"0.1.0\"\n",
        encoding="utf-8",
    )
    (destination / "src").mkdir()
    (destination / "src/lib.rs").write_text("pub fn ok() {}\n", encoding="utf-8")
    core = repo / "crates/originweave-core"
    core.mkdir(parents=True)
    (core / "Cargo.toml").write_text(
        "[package]\nname = \"originweave-core\"\nversion = \"0.1.0\"\n",
        encoding="utf-8",
    )
    git(repo, "add", ".")
    git(repo, "commit", "-m", "workspace")
    return repo


def test_originweave_workspace_selects_rustup_1_97(tmp_path: Path) -> None:
    """A 1.97 rust-toolchain.toml is a rustup install, not Debian rustc 1.85."""
    repo = rust_workspace(tmp_path)
    output = tmp_path / "base-rust"
    payload = materializer.materialize(repo, output)
    assert payload["rustup_channel"] == "1.97.1"
    assert payload["has_lock"] is True
    assert (output / "rust-toolchain.toml").is_file()
    assert (output / "crates/originweave-destination/Cargo.toml").is_file()
    assert not (output / "crates/originweave-destination/src/lib.rs").exists()
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["rustup_channel"] == "1.97.1"


def test_rust_version_newer_than_debian_selects_rustup(tmp_path: Path) -> None:
    """A rust-version newer than Debian rustc 1.85 selects rustup without a pin file."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "user.name", "Test")
    git(repo, "config", "user.email", "test@example.invalid")
    (repo / "Cargo.toml").write_text(
        "[package]\nname = \"newer\"\nversion = \"0.1.0\"\nrust-version = \"1.97\"\n",
        encoding="utf-8",
    )
    git(repo, "add", ".")
    git(repo, "commit", "-m", "newer")
    assert materializer.declared_rust_version(repo) == "1.97"
    assert materializer.rustup_channel(repo) == "1.97"


def test_old_rust_version_keeps_debian_toolchain(tmp_path: Path) -> None:
    """A crate that Debian rustc 1.85 can build does not force rustup."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "user.name", "Test")
    git(repo, "config", "user.email", "test@example.invalid")
    (repo / "Cargo.toml").write_text(
        "[package]\nname = \"legacy\"\nversion = \"0.1.0\"\nrust-version = \"1.80\"\n",
        encoding="utf-8",
    )
    git(repo, "add", ".")
    git(repo, "commit", "-m", "legacy")
    assert materializer.rustup_channel(repo) is None


def test_legacy_rust_toolchain_file(tmp_path: Path) -> None:
    """A one-line rust-toolchain file is accepted as the rustup channel."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "user.name", "Test")
    git(repo, "config", "user.email", "test@example.invalid")
    (repo / "Cargo.toml").write_text("[package]\nname = \"x\"\nversion = \"0.1.0\"\n", encoding="utf-8")
    (repo / "rust-toolchain").write_text("nightly-2026-08-01\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "nightly")
    assert materializer.toolchain_channel(repo) == "nightly-2026-08-01"
    assert materializer.rustup_channel(repo) == "nightly-2026-08-01"


def test_no_cargo_toml_writes_empty_manifest(tmp_path: Path) -> None:
    """Python-only trees do not install a Rust toolchain."""
    repo = tmp_path / "repo"
    repo.mkdir()
    payload = materializer.materialize(repo, tmp_path / "out")
    assert payload["rustup_channel"] is None
    assert payload["has_manifest"] is False
    assert payload["inputs"] == []


def test_rejects_parent_directory_workspace_member(tmp_path: Path) -> None:
    """Workspace members cannot escape the repository root."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "Cargo.toml").write_text(
        "[workspace]\nmembers = [\"../escape\"]\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="bounded path"):
        materializer.workspace_member_manifests(repo)


def test_rejects_symlink_input(tmp_path: Path) -> None:
    """Symlinked Cargo inputs cannot enter the trusted image context."""
    repo = rust_workspace(tmp_path)
    target = tmp_path / "outside.toml"
    target.write_text("[package]\n", encoding="utf-8")
    (repo / "Cargo.lock").unlink()
    (repo / "Cargo.lock").symlink_to(target)
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "symlink")
    with pytest.raises(ValueError, match="non-regular"):
        materializer.materialize(repo, tmp_path / "out")


def test_cli_and_entrypoint(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The workflow CLI prints the manifest and the script entrypoint succeeds."""
    repo = rust_workspace(tmp_path)
    output = tmp_path / "cli-out"
    assert materializer.main(["--repo-root", str(repo), "--output-dir", str(output)]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["rustup_channel"] == "1.97.1"

    monkeypatch.setattr(
        sys,
        "argv",
        [materializer.__file__, "--repo-root", str(repo), "--output-dir", str(tmp_path / "entry")],
    )
    with pytest.raises(SystemExit, match="0"):
        runpy.run_path(materializer.__file__, run_name="__main__")


def test_parse_rust_version_helpers() -> None:
    """Version parsing distinguishes Debian rustc from newer rust-version pins."""
    assert materializer.parse_rust_version("1.97") == (1, 97, 0)
    assert materializer.parse_rust_version("1.85.0") == (1, 85, 0)
    assert materializer.parse_rust_version("nightly") is None
    assert materializer.parse_rust_version("1.97") > materializer.DEBIAN_RUSTC


def test_workspace_glob_members_copy_crate_manifests(tmp_path: Path) -> None:
    """A trailing crates/* glob copies each member Cargo.toml without sources."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "user.name", "Test")
    git(repo, "config", "user.email", "test@example.invalid")
    (repo / "Cargo.toml").write_text(
        '[workspace]\nmembers = ["crates/*"]\n',
        encoding="utf-8",
    )
    crate = repo / "crates/originweave-destination"
    crate.mkdir(parents=True)
    (crate / "Cargo.toml").write_text(
        "[package]\nname = \"originweave-destination\"\nversion = \"0.1.0\"\n",
        encoding="utf-8",
    )
    (crate / "src").mkdir()
    (crate / "src/lib.rs").write_text("pub fn ok() {}\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "glob")
    output = tmp_path / "out"
    payload = materializer.materialize(repo, output)
    assert "crates/originweave-destination/Cargo.toml" in payload["inputs"]
    assert (output / "crates/originweave-destination/Cargo.toml").is_file()
    assert not (output / "crates/originweave-destination/src/lib.rs").exists()


def test_unsupported_workspace_glob_fails_closed(tmp_path: Path) -> None:
    """Recursive or in-segment globs are not trusted image inputs."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "Cargo.toml").write_text(
        '[workspace]\nmembers = ["crates/**"]\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unsupported workspace member glob"):
        materializer.workspace_member_manifests(repo)
    (repo / "Cargo.toml").write_text(
        '[workspace]\nmembers = ["cr*tes/foo"]\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unsupported workspace member glob"):
        materializer.workspace_member_manifests(repo)


def test_non_git_repo_with_cargo_toml_fails_closed(tmp_path: Path) -> None:
    """Materialization requires a readable git tree for tracked-path evidence."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "Cargo.toml").write_text("[package]\nname = \"x\"\nversion = \"0.1.0\"\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        materializer.main(["--repo-root", str(repo), "--output-dir", str(tmp_path / "out")])


def test_read_toml_requires_a_table(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A TOML document that is not a table cannot describe a Cargo workspace."""
    path = tmp_path / "Cargo.toml"
    path.write_text("[package]\nname = \"x\"\n", encoding="utf-8")
    monkeypatch.setattr(materializer.tomllib, "loads", lambda _text: ["not-a-table"])
    with pytest.raises(ValueError, match="TOML table"):
        materializer.read_toml(path)


def test_invalid_toml_and_channel(tmp_path: Path) -> None:
    """Non-table manifests and unsafe toolchain channels fail closed."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "Cargo.toml").write_text("[]\n", encoding="utf-8")
    with pytest.raises(materializer.tomllib.TOMLDecodeError):
        materializer.read_toml(repo / "Cargo.toml")
    (repo / "Cargo.toml").write_text("[workspace]\nmembers = [1]\n", encoding="utf-8")
    assert materializer.workspace_member_manifests(repo) == []
    (repo / "rust-toolchain.toml").write_text(
        '[toolchain]\nchannel = "../evil"\n',
        encoding="utf-8",
    )
    assert materializer.toolchain_channel(repo) is None
    (repo / "rust-toolchain").write_text("not a channel!\n", encoding="utf-8")
    assert materializer.toolchain_channel(repo) is None


def test_empty_glob_directory_and_missing_member(tmp_path: Path) -> None:
    """Missing glob parents and absent member directories yield no manifests."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "Cargo.toml").write_text(
        '[workspace]\nmembers = ["crates/*", "missing-crate"]\n',
        encoding="utf-8",
    )
    assert materializer.workspace_member_manifests(repo) == []


def test_symlink_glob_parent_is_ignored(tmp_path: Path) -> None:
    """A symlinked crates/ directory cannot expand workspace members."""
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "crate").mkdir()
    (outside / "crate/Cargo.toml").write_text("[package]\nname = \"x\"\nversion = \"0.1.0\"\n", encoding="utf-8")
    (repo / "crates").symlink_to(outside)
    assert materializer.expand_workspace_member(repo, "crates/*") == []


def test_non_numeric_rust_version_does_not_select_rustup(tmp_path: Path) -> None:
    """A rust-version channel name is not treated as newer than Debian rustc."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "user.name", "Test")
    git(repo, "config", "user.email", "test@example.invalid")
    (repo / "Cargo.toml").write_text(
        "[package]\nname = \"stable\"\nversion = \"0.1.0\"\nrust-version = \"stable\"\n",
        encoding="utf-8",
    )
    git(repo, "add", ".")
    git(repo, "commit", "-m", "stable")
    assert materializer.declared_rust_version(repo) == "stable"
    assert materializer.rustup_channel(repo) is None


def test_symlink_manifest_and_non_list_members(tmp_path: Path) -> None:
    """Symlinked manifests and non-list workspace members yield no rustup inputs."""
    repo = tmp_path / "repo"
    repo.mkdir()
    target = tmp_path / "outside.toml"
    target.write_text("[package]\nname = \"x\"\nversion = \"0.1.0\"\n", encoding="utf-8")
    (repo / "Cargo.toml").symlink_to(target)
    assert materializer.declared_rust_version(repo) is None
    assert materializer.workspace_member_manifests(repo) == []
    (repo / "Cargo.toml").unlink()
    (repo / "Cargo.toml").write_text("[workspace]\nmembers = \"crates/*\"\n", encoding="utf-8")
    assert materializer.workspace_member_manifests(repo) == []


def test_glob_skips_non_crate_children_and_unsafe_git_paths(tmp_path: Path) -> None:
    """Glob expansion ignores files, symlinked crates, and unsafe git paths."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "user.name", "Test")
    git(repo, "config", "user.email", "test@example.invalid")
    crates = repo / "crates"
    crates.mkdir()
    (crates / "README").write_text("not a crate\n", encoding="utf-8")
    linked = tmp_path / "linked-crate"
    linked.mkdir()
    (linked / "Cargo.toml").write_text("[package]\nname = \"x\"\nversion = \"0.1.0\"\n", encoding="utf-8")
    (crates / "linked").symlink_to(linked)
    empty = crates / "empty"
    empty.mkdir()
    (empty / "Cargo.toml").symlink_to(linked / "Cargo.toml")
    (repo / "Cargo.toml").write_text('[workspace]\nmembers = ["crates/*"]\n', encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "glob-skips")
    assert materializer.expand_workspace_member(repo, "crates/*") == []
    listed = materializer.tracked_paths(repo)
    assert all(".." not in path and not path.startswith("/") for path in listed)


def test_declared_version_without_manifest_and_unsafe_tracked_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Missing manifests and git paths with traversal do not enter the image."""
    assert materializer.declared_rust_version(tmp_path) is None
    monkeypatch.setattr(
        materializer,
        "_git",
        lambda *_args, **_kwargs: b"../escape\0/abs/Cargo.toml\0Cargo.toml\0",
    )
    assert materializer.tracked_paths(tmp_path) == {"Cargo.toml"}


def test_git_index_reader_rejects_unsafe_and_truncated_trees(tmp_path: Path) -> None:
    """Tracked-path evidence fails closed when the git dir or index is unusable."""
    repo = tmp_path / "repo"
    repo.mkdir()
    with pytest.raises(RuntimeError, match="not a git repository"):
        materializer.tracked_paths(repo)

    git_link = repo / ".git"
    git_link.symlink_to(tmp_path)
    with pytest.raises(RuntimeError, match="symbolic link"):
        materializer.tracked_paths(repo)
    git_link.unlink()

    git_link.write_text("not a pointer\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="invalid gitdir pointer"):
        materializer.tracked_paths(repo)

    missing_dir = tmp_path / "missing-git"
    git_link.write_text(f"gitdir: {missing_dir}\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="not a regular directory"):
        materializer.tracked_paths(repo)

    linked_dir = tmp_path / "linked-git"
    linked_dir.symlink_to(tmp_path)
    git_link.write_text("gitdir: linked-git\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="not a regular directory"):
        materializer.tracked_paths(repo)
    git_link.unlink()
    linked_dir.unlink()

    git_dir = repo / ".git"
    git_dir.mkdir()
    with pytest.raises(RuntimeError, match="git index is not a regular file"):
        materializer.tracked_paths(repo)
    index = git_dir / "index"
    index.symlink_to(tmp_path / "outside-index")
    with pytest.raises(RuntimeError, match="git index is not a regular file"):
        materializer.tracked_paths(repo)
    index.unlink()

    index.write_bytes(b"NOPE")
    with pytest.raises(RuntimeError, match="header is invalid"):
        materializer.tracked_paths(repo)
    index.write_bytes(_git_index([b"Cargo.toml"], version=4))
    with pytest.raises(RuntimeError, match="unsupported git index version"):
        materializer.tracked_paths(repo)
    index.write_bytes(b"DIRC" + struct.pack(">II", 2, 1))
    with pytest.raises(RuntimeError, match="truncated git index"):
        materializer.tracked_paths(repo)
    index.write_bytes(b"DIRC" + struct.pack(">II", 2, 1) + b"\0" * 60 + struct.pack(">H", 0x4000))
    with pytest.raises(RuntimeError, match="truncated git index"):
        materializer.tracked_paths(repo)
    index.write_bytes(b"DIRC" + struct.pack(">II", 2, 1) + b"\0" * 60 + struct.pack(">H", 20))
    with pytest.raises(RuntimeError, match="truncated git index path"):
        materializer.tracked_paths(repo)
    index.write_bytes(b"DIRC" + struct.pack(">II", 2, 1) + b"\0" * 60 + struct.pack(">H", 0x0FFF))
    with pytest.raises(RuntimeError, match="truncated git index path"):
        materializer.tracked_paths(repo)

    with pytest.raises(RuntimeError, match="unsupported invocation"):
        materializer._git(repo, "status")
    with pytest.raises(RuntimeError, match="unsupported invocation"):
        materializer._git(repo)
    index.write_bytes(_git_index([]))
    assert materializer.tracked_paths(repo) == set()


def test_git_index_reader_parses_extended_and_long_names(tmp_path: Path) -> None:
    """Index v3 extended entries and 0xFFF-length names still yield bounded paths."""
    repo = tmp_path / "repo"
    git_dir = repo / ".git"
    git_dir.mkdir(parents=True)
    long_name = b"crates/" + (b"a" * 20) + b"/Cargo.toml"
    (git_dir / "index").write_bytes(_git_index([long_name], version=3, extended=True))
    assert materializer.tracked_paths(repo) == {long_name.decode("ascii")}

    flags = 0x0FFF
    header = b"\0" * 60 + struct.pack(">H", flags)
    payload = header + long_name + b"\0"
    payload += b"\0" * ((8 - (len(payload) % 8)) % 8)
    (git_dir / "index").write_bytes(b"DIRC" + struct.pack(">II", 2, 1) + payload)
    assert materializer.tracked_paths(repo) == {long_name.decode("ascii")}


def test_gitdir_pointer_reads_real_index(tmp_path: Path) -> None:
    """A gitdir pointer file still exposes tracked rust inputs."""
    repo = rust_workspace(tmp_path)
    moved = tmp_path / "real-git"
    (repo / ".git").rename(moved)
    (repo / ".git").write_text(f"gitdir: {moved}\n", encoding="utf-8")
    assert "Cargo.toml" in materializer.tracked_paths(repo)


def test_invalid_toml_decode_fails_cli(tmp_path: Path) -> None:
    """Corrupt Cargo.toml fails the materializer CLI instead of building an image."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "user.name", "Test")
    git(repo, "config", "user.email", "test@example.invalid")
    (repo / "Cargo.toml").write_text("this is not toml [[[\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "corrupt")
    with pytest.raises(SystemExit):
        materializer.main(["--repo-root", str(repo), "--output-dir", str(tmp_path / "out")])
