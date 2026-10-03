"""Contract: the coverage sandbox builds a PyO3/maturin extension fully offline.

Reproduces the sandbox shape fast-mlsirm#1907 hit: `python3 -m coverage run -m pytest` failed
collection with `ImportError: cannot import name '_core'` because nothing in the
`--network=none` coverage container ever built the compiled extension. This exercises the same
two steps the workflow's `build_maturin_extension_if_needed` helper
(.github/workflows/opencode-review-dispatch.yml) performs -- vendor the *base* commit's Cargo
dependencies with materialize_base_rust_dependencies.py, then run
`maturin build --offline` against that vendor directory -- and proves both that the import
succeeds afterward and that a dependency only a pull request added is never fetched.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.ci import materialize_base_rust_dependencies as materializer

def _maturin_importable() -> bool:
    """Return whether ``sys.executable`` (the interpreter these tests run under) has maturin."""
    return (
        subprocess.run(
            [sys.executable, "-c", "import maturin"], capture_output=True
        ).returncode
        == 0
    )


pytestmark = pytest.mark.skipif(
    shutil.which("cargo") is None or shutil.which("rustc") is None or not _maturin_importable(),
    reason="cargo, rustc, and an importable maturin module are required to build a real PyO3 extension",
)

_PYPROJECT_TOML = """\
[build-system]
requires = ["maturin>=1,<2"]
build-backend = "maturin"

[project]
name = "fixture_core"
version = "0.1.0"
requires-python = ">=3.10"

[tool.maturin]
module-name = "fixture_core._core"
"""

_CARGO_TOML = """\
[package]
name = "fixture_core"
version = "0.1.0"
edition = "2021"

[lib]
name = "_core"
crate-type = ["cdylib"]

[dependencies]
pyo3 = {{ version = "0.22", features = ["extension-module", "abi3-py310"] }}
{extra_dependency}
"""

_LIB_RS = """\
use pyo3::prelude::*;

#[pyfunction]
fn ping() -> i64 {{ 42 }}

#[pymodule]
fn _core(m: &Bound<'_, PyModule>) -> PyResult<()> {{
    m.add_function(wrap_pyfunction!(ping, m)?)?;
    Ok(())
}}
"""


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _init_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "user.email", "test@example.invalid")


def _write_fixture_project(repo: Path, *, extra_dependency: str = "") -> None:
    (repo / "pyproject.toml").write_text(_PYPROJECT_TOML, encoding="utf-8")
    (repo / "Cargo.toml").write_text(
        _CARGO_TOML.format(extra_dependency=extra_dependency), encoding="utf-8"
    )
    src_dir = repo / "src"
    src_dir.mkdir(exist_ok=True)
    (src_dir / "lib.rs").write_text(_LIB_RS, encoding="utf-8")
    package_dir = repo / "fixture_core"
    package_dir.mkdir(exist_ok=True)
    (package_dir / "__init__.py").touch()
    subprocess.run(
        ["cargo", "generate-lockfile"], cwd=repo, check=True, capture_output=True
    )


def _commit_all(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _build_offline(
    repo: Path, cargo_home: Path, vendor_output: Path, final_vendor_dir: Path, dist_dir: Path
) -> subprocess.CompletedProcess[str]:
    """Run the exact offline build the sandbox's coverage step performs.

    Mirrors the workflow: materialization runs on the runner at ``vendor_output``, then the
    ``base-rust-dependencies`` directory is copied into the trusted image at the fixed path
    the baked ``cargo-config.toml`` names (``final_vendor_dir`` here).
    """
    cargo_home.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(vendor_output / "cargo-config.toml", cargo_home / "config.toml")
    shutil.copytree(vendor_output / "vendor", final_vendor_dir)
    return subprocess.run(
        [sys.executable, "-m", "maturin", "build", "--offline", "--release", "-o", str(dist_dir)],
        cwd=repo,
        env={
            "PATH": __import__("os").environ["PATH"],
            "HOME": __import__("os").environ.get("HOME", "/tmp"),
            "CARGO_HOME": str(cargo_home),
            "CARGO_NET_OFFLINE": "true",
            "CARGO_BUILD_JOBS": "1",
        },
        capture_output=True,
        text=True,
        timeout=600,
    )


def test_offline_build_and_import_of_pyo3_extension_succeeds(tmp_path: Path) -> None:
    """The vendored-offline build produces an importable `_core` extension module."""
    repo = tmp_path / "fixture-repo"
    _init_repo(repo)
    _write_fixture_project(repo)
    base_sha = _commit_all(repo, "base commit")

    vendor_output = tmp_path / "vendor-output"
    final_vendor_dir = tmp_path / "final-vendor-location"
    materializer.materialize(
        repo, base_sha, vendor_output, vendor_dir_for_config=str(final_vendor_dir)
    )
    assert (vendor_output / "vendor").is_dir()
    assert final_vendor_dir.as_posix() in (vendor_output / "cargo-config.toml").read_text(
        "utf-8"
    )

    cargo_home = tmp_path / "cargo-home"
    dist_dir = tmp_path / "dist"
    result = _build_offline(repo, cargo_home, vendor_output, final_vendor_dir, dist_dir)
    assert result.returncode == 0, result.stderr

    wheels = list(dist_dir.glob("*.whl"))
    assert len(wheels) == 1

    install_root = tmp_path / "install-root"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-index",
            "--no-deps",
            "--target",
            str(install_root),
            str(wheels[0]),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    check = subprocess.run(
        [sys.executable, "-c", "from fixture_core import _core; print(_core.ping())"],
        cwd=tmp_path,
        env={"PYTHONPATH": str(install_root)},
        capture_output=True,
        text=True,
    )
    assert check.returncode == 0, check.stderr
    assert check.stdout.strip() == "42"


def test_pull_request_added_dependency_is_never_fetched_offline(tmp_path: Path) -> None:
    """A dependency only the PR head added must not be silently fetched offline."""
    repo = tmp_path / "fixture-repo"
    _init_repo(repo)
    _write_fixture_project(repo)
    base_sha = _commit_all(repo, "base commit")

    # Simulate a pull request that adds a new Cargo dependency the trusted base
    # materializer never saw and therefore never vendored.
    _write_fixture_project(repo, extra_dependency='itoa = "1"')
    (repo / "src" / "lib.rs").write_text(
        _LIB_RS.replace(
            "fn ping() -> i64 {{ 42 }}",
            'fn ping() -> i64 {{ itoa::Buffer::new().format(42i64).len() as i64 }}',
        ),
        encoding="utf-8",
    )
    subprocess.run(["cargo", "generate-lockfile"], cwd=repo, check=True, capture_output=True)
    _commit_all(repo, "pull request adds a new Cargo dependency")

    vendor_output = tmp_path / "vendor-output"
    final_vendor_dir = tmp_path / "final-vendor-location"
    materializer.materialize(
        repo, base_sha, vendor_output, vendor_dir_for_config=str(final_vendor_dir)
    )

    vendor_crate_names = {
        entry.name.rsplit("-", 1)[0] for entry in (vendor_output / "vendor").iterdir()
    }
    assert "itoa" not in vendor_crate_names

    cargo_home = tmp_path / "cargo-home"
    dist_dir = tmp_path / "dist"
    result = _build_offline(repo, cargo_home, vendor_output, final_vendor_dir, dist_dir)

    assert result.returncode != 0
    combined_output = result.stdout + result.stderr
    assert "itoa" in combined_output
    assert not list(dist_dir.glob("*.whl"))
