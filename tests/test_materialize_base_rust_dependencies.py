from __future__ import annotations

import json
import runpy
import shutil
import subprocess
from pathlib import Path

import pytest

from scripts.ci import materialize_base_rust_dependencies as materializer

pytestmark = pytest.mark.skipif(
    shutil.which("cargo") is None, reason="cargo is required to vendor a real dependency graph"
)


def git(repo: Path, *args: str) -> str:
    """Run git in a temporary fixture repository."""
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _init_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    git(repo, "init")
    git(repo, "config", "user.name", "Test")
    git(repo, "config", "user.email", "test@example.invalid")


def _commit_all(repo: Path) -> str:
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "materialize fixture")
    return git(repo, "rev-parse", "HEAD")


def _write_single_crate_workspace(repo: Path) -> None:
    (repo / "Cargo.toml").write_text(
        '[workspace]\nmembers = ["crates/foo"]\nresolver = "2"\n', encoding="utf-8"
    )
    crate_dir = repo / "crates" / "foo"
    crate_dir.mkdir(parents=True)
    (crate_dir / "Cargo.toml").write_text(
        '[package]\nname = "foo"\nversion = "0.1.0"\nedition = "2021"\n\n'
        '[dependencies]\nitoa = "1"\n',
        encoding="utf-8",
    )
    src_dir = crate_dir / "src"
    src_dir.mkdir()
    (src_dir / "lib.rs").write_text("pub fn x() {}\n", encoding="utf-8")
    subprocess.run(
        ["cargo", "generate-lockfile"], cwd=repo, check=True, capture_output=True
    )


def test_no_tracked_cargo_lock_skips_gracefully(tmp_path: Path) -> None:
    """Repositories with no Rust code produce an empty manifest, not an error."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "README.md").write_text("hi\n", encoding="utf-8")
    base_sha = _commit_all(repo)

    output_dir = tmp_path / "out"
    manifest = materializer.materialize(repo, base_sha, output_dir)

    assert manifest == []
    assert json.loads((output_dir / "manifest.json").read_text()) == []
    assert not (output_dir / "vendor").exists()


def test_vendors_a_single_workspace_offline_afterward(tmp_path: Path) -> None:
    """A workspace's locked dependency closure vendors, and cargo then builds offline from it."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write_single_crate_workspace(repo)
    base_sha = _commit_all(repo)

    output_dir = tmp_path / "out"
    manifest = materializer.materialize(
        repo, base_sha, output_dir, vendor_dir_for_config=str(output_dir / "vendor")
    )

    assert manifest == ["Cargo.lock"]
    vendored_crates = {p.name.rsplit("-", 1)[0] for p in (output_dir / "vendor").iterdir()}
    assert "itoa" in vendored_crates
    config_text = (output_dir / "cargo-config.toml").read_text()
    assert str(output_dir / "vendor") in config_text

    cargo_home = tmp_path / "cargo-home"
    cargo_home.mkdir()
    (cargo_home / "config.toml").write_text(config_text, encoding="utf-8")
    build = subprocess.run(
        ["cargo", "build", "--offline"],
        cwd=repo,
        env={**__import__("os").environ, "CARGO_HOME": str(cargo_home), "CARGO_NET_OFFLINE": "true"},
        capture_output=True,
        text=True,
    )
    assert build.returncode == 0, build.stderr


def test_pr_added_dependency_not_in_base_lock_is_not_materialized(tmp_path: Path) -> None:
    """Vendoring reads only the validated base commit, never a later PR-controlled lock."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write_single_crate_workspace(repo)
    base_sha = _commit_all(repo)

    crate_toml = repo / "crates" / "foo" / "Cargo.toml"
    crate_toml.write_text(
        crate_toml.read_text().replace('itoa = "1"', 'itoa = "1"\nryu = "1"'), encoding="utf-8"
    )
    subprocess.run(["cargo", "generate-lockfile"], cwd=repo, check=True, capture_output=True)
    _commit_all(repo)

    output_dir = tmp_path / "out"
    manifest = materializer.materialize(repo, base_sha, output_dir)

    assert manifest == ["Cargo.lock"]
    vendored_crates = {p.name.rsplit("-", 1)[0] for p in (output_dir / "vendor").iterdir()}
    assert "ryu" not in vendored_crates


def test_multiple_workspace_roots_are_vendored_as_a_union(tmp_path: Path) -> None:
    """Several base lock roots are all vendored, because their closures differ.

    The standard cargo-fuzz layout declares ``[workspace]`` in the repository root and
    in ``fuzz/`` so the fuzz crate opts out of the parent workspace, and the two locks
    resolve different crate sets. Selecting one root and dropping the rest would vendor
    an incomplete closure, which is why this is a union rather than a refusal.
    """
    repo = tmp_path / "repo"
    _init_repo(repo)
    for name in ("a", "b"):
        crate_dir = repo / name
        crate_dir.mkdir()
        (crate_dir / "Cargo.toml").write_text(
            f'[workspace]\nmembers = ["{name}-crate"]\n', encoding="utf-8"
        )
        (crate_dir / "Cargo.lock").write_text("# empty lock\n", encoding="utf-8")
    base_sha = _commit_all(repo)

    roots = materializer._select_vendor_roots(repo, base_sha, ["a/Cargo.toml", "a/Cargo.lock", "b/Cargo.toml", "b/Cargo.lock"])
    assert roots == ["a", "b"]


def test_root_and_fuzz_vendor_distinct_crates_and_reject_changed_or_missing_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real two-root Cargo path retains both closures and rejects lock drift."""
    monkeypatch.setenv("CARGO_HOME", str(tmp_path / "cargo-home"))
    dependencies = {}
    for name in ("rootdep", "fuzzdep"):
        dependency = tmp_path / name
        _init_repo(dependency)
        (dependency / "Cargo.toml").write_text(
            f'[package]\nname = "{name}"\nversion = "0.1.0"\nedition = "2021"\n',
            encoding="utf-8",
        )
        (dependency / "src").mkdir()
        (dependency / "src" / "lib.rs").write_text("pub fn marker() {}\n", encoding="utf-8")
        _commit_all(dependency)
        dependencies[name] = dependency.as_uri()

    repo = tmp_path / "repo"
    _init_repo(repo)
    for directory, package, dependency in (
        (repo, "root", "rootdep"),
        (repo / "fuzz", "fuzz", "fuzzdep"),
    ):
        directory.mkdir(exist_ok=True)
        (directory / "Cargo.toml").write_text(
            f'[package]\nname = "{package}"\nversion = "0.1.0"\nedition = "2021"\n'
            f'[workspace]\n[dependencies]\n{dependency} = {{ git = "{dependencies[dependency]}" }}\n',
            encoding="utf-8",
        )
        (directory / "src").mkdir()
        (directory / "src" / "lib.rs").write_text("pub fn marker() {}\n", encoding="utf-8")
        subprocess.run(
            ["cargo", "generate-lockfile"],
            cwd=directory,
            check=True,
            capture_output=True,
        )
    base_sha = _commit_all(repo)
    monkeypatch.setenv("CARGO_NET_OFFLINE", "true")

    output_dir = tmp_path / "out"
    assert materializer.materialize(repo, base_sha, output_dir) == [
        "Cargo.lock", "fuzz/Cargo.lock"
    ]
    assert json.loads((output_dir / "manifest.json").read_text()) == [
        "Cargo.lock", "fuzz/Cargo.lock"
    ]
    vendored = {path.name.split("-")[0] for path in (output_dir / "vendor").iterdir()}
    assert {"rootdep", "fuzzdep"} <= vendored

    fuzz_lock = repo / "fuzz" / "Cargo.lock"
    lock_text = fuzz_lock.read_text(encoding="utf-8")
    assert 'name = "fuzzdep"' in lock_text
    fuzz_lock.write_text(lock_text.replace('name = "fuzzdep"', 'name = "otherdep"', 1))
    changed_sha = _commit_all(repo)
    with pytest.raises(RuntimeError, match="cargo vendor failed.*fuzz/Cargo.lock"):
        materializer.materialize(repo, changed_sha, tmp_path / "changed")

    fuzz_lock.unlink()
    missing_sha = _commit_all(repo)
    with pytest.raises(RuntimeError, match="fuzz.*no sibling Cargo.lock"):
        materializer.materialize(repo, missing_sha, tmp_path / "missing")


def test_the_repository_root_is_the_primary_manifest_when_present() -> None:
    """Ordering is deterministic and puts the repository root first."""
    roots = materializer._select_vendor_roots.__wrapped__ if False else None  # noqa: F841
    paths = ["Cargo.toml", "Cargo.lock", "fuzz/Cargo.toml", "fuzz/Cargo.lock"]
    import unittest.mock as mock

    with mock.patch.object(materializer, "_git", return_value=b"[workspace]\n"):
        assert materializer._select_vendor_roots(Path("/unused"), "a" * 40, paths) == [
            ".",
            "fuzz",
        ]


def test_vendor_command_asserts_every_lock_and_syncs_every_root() -> None:
    """The union must reach cargo as --sync, and every lock must be asserted.

    Without ``--locked`` cargo may re-resolve a lock that disagrees with its manifest,
    so the vendored set would no longer be the committed closure; without ``--sync``
    only the primary root's dependencies would be vendored.
    """
    import unittest.mock as mock

    with mock.patch.object(materializer.subprocess, "run") as runner:
        runner.return_value = materializer.subprocess.CompletedProcess([], 0, b"", b"")
        materializer._run_cargo_vendor(
            Path("/work/Cargo.toml"),
            Path("/out/vendor"),
            [Path("/work/fuzz/Cargo.toml")],
        )
    command = runner.call_args.args[0]
    assert command[:3] == ["cargo", "vendor", "--locked"]
    assert command[command.index("--manifest-path") + 1] == "/work/Cargo.toml"
    assert command[command.index("--sync") + 1] == "/work/fuzz/Cargo.toml"
    assert command[-1] == "/out/vendor"


def test_main_reports_error_and_exits_nonzero_on_failure(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The CLI surfaces a materialization failure as ``::error::`` and exit code 1."""
    repo = tmp_path / "not-a-git-repo"
    repo.mkdir()

    exit_code = materializer.main(
        [
            "--repo-root",
            str(repo),
            "--base-sha",
            "a" * 40,
            "--output-dir",
            str(tmp_path / "out"),
        ]
    )

    assert exit_code == 1
    assert "::error::Could not materialize base Rust dependencies" in capsys.readouterr().err


def test_main_reports_success_with_no_rust_project(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The CLI reports a clean skip for a repository with no Rust code."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "README.md").write_text("hi\n", encoding="utf-8")
    base_sha = _commit_all(repo)

    exit_code = materializer.main(
        [
            "--repo-root",
            str(repo),
            "--base-sha",
            base_sha,
            "--output-dir",
            str(tmp_path / "out"),
        ]
    )

    assert exit_code == 0
    assert "Rust vendoring skipped" in capsys.readouterr().out


def test_main_reports_success_with_a_vendored_workspace(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The CLI names the vendored base lock file on a successful run."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write_single_crate_workspace(repo)
    base_sha = _commit_all(repo)

    exit_code = materializer.main(
        [
            "--repo-root",
            str(repo),
            "--base-sha",
            base_sha,
            "--output-dir",
            str(tmp_path / "out"),
        ]
    )

    assert exit_code == 0
    assert "Materialized trusted base Cargo vendor directory from Cargo.lock." in (
        capsys.readouterr().out
    )


def test_module_entry_point_runs_main(monkeypatch: pytest.MonkeyPatch) -> None:
    """``python -m`` execution reaches ``main`` and propagates its exit code."""
    monkeypatch.setattr("sys.argv", ["materialize_base_rust_dependencies.py"])
    with pytest.raises(SystemExit) as excinfo:
        runpy.run_path(
            str(Path(materializer.__file__)), run_name="__main__"
        )
    assert excinfo.value.code == 2  # argparse: missing required arguments


def test_malformed_ls_tree_entry_without_tab_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """A git ls-tree entry with no ``<tab>`` separator is a git-format integrity failure."""
    monkeypatch.setattr(materializer, "_git", lambda *_a, **_k: b"bogus-entry-with-no-tab")
    with pytest.raises(RuntimeError, match="malformed entry"):
        materializer._regular_cargo_blob_paths(Path("/unused"), "a" * 40)


def test_malformed_ls_tree_metadata_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """A git ls-tree entry with the wrong metadata field count is rejected."""
    monkeypatch.setattr(materializer, "_git", lambda *_a, **_k: b"100644 blob\tCargo.toml")
    with pytest.raises(RuntimeError, match="malformed metadata"):
        materializer._regular_cargo_blob_paths(Path("/unused"), "a" * 40)


def test_symlinked_cargo_toml_is_excluded(tmp_path: Path) -> None:
    """A tracked symlink named ``Cargo.toml`` is never treated as a candidate manifest."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write_single_crate_workspace(repo)
    (repo / "linked-crate").symlink_to("crates/foo")
    base_sha = _commit_all(repo)

    paths = materializer._regular_cargo_blob_paths(repo, base_sha)

    assert "linked-crate/Cargo.toml" not in paths
    assert "Cargo.toml" in paths


def test_is_workspace_manifest_rejects_invalid_toml() -> None:
    """An unparseable base ``Cargo.toml`` fails closed instead of being treated as non-workspace."""
    with pytest.raises(RuntimeError, match="could not parse"):
        materializer._is_workspace_manifest(b"not = [valid toml")


def test_select_vendor_root_workspace_without_sibling_lock_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A workspace root manifest with no ``Cargo.lock`` next to it fails closed."""
    monkeypatch.setattr(
        materializer, "_git", lambda *_a, **_k: b'[workspace]\nmembers = ["crates/foo"]\n'
    )
    with pytest.raises(RuntimeError, match="no sibling Cargo.lock"):
        materializer._select_vendor_roots(Path("/unused"), "a" * 40, ["Cargo.toml"])


def test_select_vendor_root_returns_single_standalone_crate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A single crate with no ``[workspace]`` table is its own vendor root."""
    monkeypatch.setattr(materializer, "_git", lambda *_a, **_k: b'[package]\nname = "foo"\n')
    roots = materializer._select_vendor_roots(
        Path("/unused"), "a" * 40, ["crate-a/Cargo.toml", "crate-a/Cargo.lock"]
    )
    assert roots == ["crate-a"]


def test_select_vendor_root_single_lock_without_manifest_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A standalone ``Cargo.lock`` with no sibling ``Cargo.toml`` fails closed."""
    monkeypatch.setattr(materializer, "_git", lambda *_a, **_k: b"")
    with pytest.raises(RuntimeError, match="no sibling Cargo.toml"):
        materializer._select_vendor_roots(Path("/unused"), "a" * 40, ["crate-a/Cargo.lock"])


def test_select_vendor_roots_covers_independent_standalone_crates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two independent crates are both vendored; neither lock may be dropped.

    ``--sync`` vendors any set of manifests into one directory, so nesting is not
    required for the union to be correct and there is nothing left to guess.
    """
    monkeypatch.setattr(materializer, "_git", lambda *_a, **_k: b'[package]\nname = "x"\n')
    assert materializer._select_vendor_roots(
        Path("/unused"),
        "a" * 40,
        ["crate-a/Cargo.toml", "crate-a/Cargo.lock", "crate-b/Cargo.toml", "crate-b/Cargo.lock"],
    ) == ["crate-a", "crate-b"]


def test_placeholder_target_paths_covers_explicit_lib_and_bin_entries() -> None:
    """Explicitly declared ``[lib]``/``[[bin]]`` paths are added alongside the conventions."""
    manifest = (
        b'[package]\nname = "foo"\nversion = "0.1.0"\n\n'
        b'[lib]\npath = "src/custom_lib.rs"\n\n'
        b'[[bin]]\nname = "cli"\npath = "src/bin/cli.rs"\n'
        b'[[bin]]\nname = "nameless"\n'
    )
    paths = materializer._placeholder_target_paths(manifest)
    assert paths == sorted(
        {"src/lib.rs", "src/main.rs", "src/custom_lib.rs", "src/bin/cli.rs"}
    )


def test_placeholder_target_paths_returns_empty_for_invalid_or_workspace_only_toml() -> None:
    """Invalid TOML and manifests with no ``[package]`` table need no placeholder targets."""
    assert materializer._placeholder_target_paths(b"not = [valid") == []
    assert materializer._placeholder_target_paths(b'[workspace]\nmembers = ["a"]\n') == []


def test_reconstruct_base_tree_does_not_overwrite_an_existing_placeholder(
    tmp_path: Path,
) -> None:
    """Running placeholder synthesis twice for the same manifest is a no-op the second time."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write_single_crate_workspace(repo)
    base_sha = _commit_all(repo)
    cargo_paths = materializer._regular_cargo_blob_paths(repo, base_sha)

    work_dir = tmp_path / "work"
    materializer._reconstruct_base_tree(repo, base_sha, cargo_paths, work_dir)
    marker = (work_dir / "crates" / "foo" / "src" / "lib.rs").read_text()
    (work_dir / "crates" / "foo" / "src" / "lib.rs").write_text("not-overwritten")
    materializer._reconstruct_base_tree(repo, base_sha, cargo_paths, work_dir)

    assert (work_dir / "crates" / "foo" / "src" / "lib.rs").read_text() == "not-overwritten"
    assert marker == ""


def test_run_cargo_vendor_propagates_missing_binary(tmp_path: Path) -> None:
    """A missing ``cargo`` executable surfaces as a materialize() ``RuntimeError``."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write_single_crate_workspace(repo)
    base_sha = _commit_all(repo)

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(
            materializer,
            "_run_cargo_vendor",
            lambda *_a, **_k: (_ for _ in ()).throw(FileNotFoundError("cargo")),
        )
        with pytest.raises(RuntimeError, match="could not run trusted cargo vendor"):
            materializer.materialize(repo, base_sha, tmp_path / "out")


def test_materialize_surfaces_cargo_vendor_failure_detail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A non-zero ``cargo vendor`` exit is reported with its captured stderr detail."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write_single_crate_workspace(repo)
    base_sha = _commit_all(repo)

    monkeypatch.setattr(
        materializer,
        "_run_cargo_vendor",
        lambda *_a, **_k: subprocess.CompletedProcess(
            args=["cargo", "vendor"], returncode=101, stdout=b"", stderr=b"boom\n"
        ),
    )
    with pytest.raises(RuntimeError, match="cargo vendor failed for base lock Cargo.lock: boom"):
        materializer.materialize(repo, base_sha, tmp_path / "out")


def test_materialize_surfaces_cargo_vendor_failure_with_no_stderr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A non-zero ``cargo vendor`` exit with empty stderr still names the exit status."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write_single_crate_workspace(repo)
    base_sha = _commit_all(repo)

    monkeypatch.setattr(
        materializer,
        "_run_cargo_vendor",
        lambda *_a, **_k: subprocess.CompletedProcess(
            args=["cargo", "vendor"], returncode=101, stdout=b"", stderr=b""
        ),
    )
    with pytest.raises(RuntimeError, match="exit status 101"):
        materializer.materialize(repo, base_sha, tmp_path / "out")


def test_materialize_rejects_bad_sha_and_symlinked_output_dir(tmp_path: Path) -> None:
    """Both input-validation guards fail closed before any git or cargo command runs."""
    with pytest.raises(ValueError, match="40 hexadecimal"):
        materializer.materialize(Path("/unused"), "not-a-sha", tmp_path / "out")

    real_dir = tmp_path / "real"
    real_dir.mkdir()
    linked_output = tmp_path / "linked-out"
    linked_output.symlink_to(real_dir)
    with pytest.raises(ValueError, match="must not be a symlink"):
        materializer.materialize(Path("/unused"), "a" * 40, linked_output)
