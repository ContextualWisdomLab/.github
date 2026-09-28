"""Contract: trusted coverage image VCS import-root resolution admits python/.

#2157: the coverage tool image aborted at docker step #17 because the inline
materializer only accepted root/`src/` layouts, while immutable
`fast-mlsirm@09f762ded` exposes `fast_mlsirm` under `python/`. #2123 admitted
those candidates on `main`; this contract keeps the resolver as an executable
helper the Dockerfile COPYs, and proves the image-path algorithm offline
against fixtures (including the live fast-mlsirm layout shape).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_HELPER = (
    _REPOSITORY_ROOT / "scripts/ci/resolve_opencode_base_vcs_import_root.sh"
)
_DISPATCH = (
    _REPOSITORY_ROOT / ".github/workflows/opencode-review-dispatch.yml"
)


def _run_resolver(
    destination: Path, import_name: str, repository: str = "fixture-pkg"
) -> subprocess.CompletedProcess[str]:
    """Invoke the trusted VCS import-root resolver against a fixture tree."""

    return subprocess.run(
        [str(_HELPER), str(destination), import_name, repository],
        capture_output=True,
        text=True,
        check=False,
    )


def test_helper_is_executable_and_wired_into_coverage_image_build() -> None:
    """The Dockerfile must COPY and execute the reviewed helper, not inline drift."""

    assert _HELPER.is_file()
    assert _HELPER.stat().st_mode & 0o111
    workflow = _DISPATCH.read_text(encoding="utf-8")
    assert "resolve_opencode_base_vcs_import_root.sh" in workflow
    assert (
        "COPY resolve-opencode-base-vcs-import-root.sh"
        " /usr/local/libexec/resolve-opencode-base-vcs-import-root.sh"
    ) in workflow
    assert 'python_root="$("$resolver" "$destination" "$import_name" "$repository")"' in workflow
    assert 'install -m 0755 "$trusted_vcs_import_root_resolver"' in workflow
    # Candidate layouts live in the helper; the Dockerfile must not re-inline them.
    assert 'candidate_count=$((candidate_count + 1))' not in workflow
    helper = _HELPER.read_text(encoding="utf-8")
    assert '"$destination/python/$import_name"' in helper
    assert '"$destination/python/$import_name.py"' in helper
    assert "has a missing or ambiguous import root" in helper


def test_python_source_root_package_layout_resolves(tmp_path: Path) -> None:
    """A maturin-style ``python/<import>/__init__.py`` tree maps to ``python/``."""

    package = tmp_path / "python" / "fast_mlsirm"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text('"""fixture"""\n', encoding="utf-8")
    result = _run_resolver(tmp_path, "fast_mlsirm", "fast-mlsirm")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(tmp_path / "python")


def test_python_source_root_single_module_resolves(tmp_path: Path) -> None:
    """A single-module ``python/<import>.py`` is also a valid conventional root."""

    python_root = tmp_path / "python"
    python_root.mkdir()
    (python_root / "fast_mlsirm.py").write_text("VALUE = 1\n", encoding="utf-8")
    result = _run_resolver(tmp_path, "fast_mlsirm", "fast-mlsirm")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(python_root)


def test_src_layout_still_resolves(tmp_path: Path) -> None:
    """Pre-existing ``src/<import>`` layouts remain admitted."""

    package = tmp_path / "src" / "demo_pkg"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text('"""fixture"""\n', encoding="utf-8")
    result = _run_resolver(tmp_path, "demo_pkg", "demo-pkg")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(tmp_path / "src")


def test_missing_import_root_fails_closed(tmp_path: Path) -> None:
    """No conventional candidate must keep failing the image build, not defer."""

    (tmp_path / "README.md").write_text("empty\n", encoding="utf-8")
    result = _run_resolver(tmp_path, "fast_mlsirm", "fast-mlsirm")
    assert result.returncode == 1
    assert (
        "locked VCS source fast-mlsirm has a missing or ambiguous import root"
        " for fast_mlsirm" in result.stderr
    )


def test_ambiguous_python_and_src_roots_fail_closed(tmp_path: Path) -> None:
    """Exactly one candidate may exist; python/ + src/ is still fatal."""

    for root in ("python", "src"):
        package = tmp_path / root / "fast_mlsirm"
        package.mkdir(parents=True)
        (package / "__init__.py").write_text('"""fixture"""\n', encoding="utf-8")
    result = _run_resolver(tmp_path, "fast_mlsirm", "fast-mlsirm")
    assert result.returncode == 1
    assert "missing or ambiguous import root" in result.stderr


def test_namespace_package_without_init_fails_closed(tmp_path: Path) -> None:
    """A directory without ``__init__.py`` is rejected as a namespace root."""

    package = tmp_path / "python" / "fast_mlsirm"
    package.mkdir(parents=True)
    (package / "mod.py").write_text("VALUE = 1\n", encoding="utf-8")
    result = _run_resolver(tmp_path, "fast_mlsirm", "fast-mlsirm")
    assert result.returncode == 1
    assert "namespace or linked import root" in result.stderr


def test_compiled_extension_in_checkout_fails_closed(tmp_path: Path) -> None:
    """Checked-in compiled artifacts must not enter the trusted .pth path."""

    package = tmp_path / "python" / "fast_mlsirm"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text('"""fixture"""\n', encoding="utf-8")
    (package / "_core.so").write_bytes(b"\x00")
    result = _run_resolver(tmp_path, "fast_mlsirm", "fast-mlsirm")
    assert result.returncode == 1
    assert "contains a compiled extension" in result.stderr


@pytest.mark.parametrize(
    ("layout", "import_file"),
    [
        ("root-package", "pkg"),
        ("root-module", "pkg.py"),
    ],
)
def test_repository_root_layouts_still_resolve(
    tmp_path: Path, layout: str, import_file: str
) -> None:
    """Root-level package and module layouts remain valid one-candidate roots."""

    del layout  # parametrize label only
    if import_file.endswith(".py"):
        (tmp_path / import_file).write_text("VALUE = 1\n", encoding="utf-8")
        import_name = import_file[: -len(".py")]
    else:
        package = tmp_path / import_file
        package.mkdir()
        (package / "__init__.py").write_text('"""fixture"""\n', encoding="utf-8")
        import_name = import_file
    result = _run_resolver(tmp_path, import_name, "root-layout")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(tmp_path)
