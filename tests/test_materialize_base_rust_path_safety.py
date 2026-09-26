from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts.ci import materialize_base_rust_dependencies as materializer


def _git(repo: Path, *arguments: str) -> str:
    """Run Git for the materializer path-safety fixture."""
    return subprocess.run(
        ["git", "-C", str(repo), *arguments],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


@pytest.mark.parametrize("absolute_target", [False, True])
def test_reconstruct_base_tree_rejects_target_path_outside_manifest_root(
    tmp_path: Path, absolute_target: bool
) -> None:
    """A trusted manifest cannot make placeholder synthesis escape its root."""
    escaped_path = tmp_path / ("absolute-escaped.rs" if absolute_target else "escaped.rs")
    target_path = str(escaped_path) if absolute_target else "zzz/../../escaped.rs"
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "user.email", "test@example.invalid")
    (repo / "Cargo.toml").write_text(
        '[package]\nname = "probe"\nversion = "0.1.0"\n'
        f'[lib]\npath = "{target_path}"\n',
        encoding="utf-8",
    )
    (repo / "Cargo.lock").write_text("# fixture lock\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "path safety fixture")
    base_sha = _git(repo, "rev-parse", "HEAD")
    work_dir = tmp_path / "work"

    with pytest.raises(RuntimeError, match="target path must stay inside its manifest root"):
        materializer._reconstruct_base_tree(
            repo,
            base_sha,
            ["Cargo.toml", "Cargo.lock"],
            work_dir,
        )

    assert not escaped_path.exists()
