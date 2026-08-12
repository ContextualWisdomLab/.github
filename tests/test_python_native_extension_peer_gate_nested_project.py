"""Nested-project regressions for the PyO3 native peer-evidence classifier."""

from __future__ import annotations

from pathlib import Path

from scripts.ci import python_native_extension_peer_gate as gate


_PYPROJECT = """\
[build-system]
requires = ["maturin>=1.10,<2.0"]
build-backend = "maturin"

[tool.maturin]
bindings = "pyo3"
manifest-path = "crates/native_bridge/Cargo.toml"
module-name = "nested_package._core"
python-source = "python"
"""

_PYTEST_LOG = """\
============================= test session starts ==============================
collected 0 items / 1 error

_____________ ERROR collecting tests/test_public_api.py ______________
ImportError while importing test module '/work/services/nested/tests/test_public_api.py'.
Traceback:
tests/test_public_api.py:3: in <module>
    import nested_package._core
E   ModuleNotFoundError: No module named 'nested_package._core'
!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
============================== 1 error in 0.20s ===============================
"""


def _write(path: Path, text: str) -> Path:
    """Write one UTF-8 fixture and return its path."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _nested_inputs(tmp_path: Path, changed: str) -> tuple[Path, Path, Path, Path]:
    """Create a repository-rooted nested maturin project fixture."""

    repository_root = tmp_path / "repository_root"
    project_root = repository_root / "services" / "nested_project"
    return (
        repository_root,
        _write(project_root / "pytest.log", _PYTEST_LOG),
        _write(project_root / "pyproject.toml", _PYPROJECT),
        _write(repository_root / "changed-files.txt", changed),
    )


def test_nested_project_python_only_change_is_classifiable(tmp_path: Path) -> None:
    """Repository-relative Python changes retain the nested project prefix."""

    repository_root, log_path, pyproject_path, changed_files_path = _nested_inputs(
        tmp_path,
        "services/nested_project/python/nested_package/reporting.py\n"
        "services/nested_project/tests/test_reporting.py\n",
    )

    assert gate.classify_pytest_inputs(
        log_path=log_path,
        pyproject_path=pyproject_path,
        changed_files_path=changed_files_path,
        repo_root_path=repository_root,
    ) == "nested_package._core"


def test_nested_project_native_and_metadata_changes_block_deferral(
    tmp_path: Path,
) -> None:
    """Nested native paths and their exact pyproject remain blocking."""

    for changed in (
        "pyproject.toml\n",
        "services/nested_project/crates/native_bridge/README.md\n",
        "services/nested_project/crates/native_bridge/src/lib.rs\n",
        "services/nested_project/pyproject.toml\n",
        "services/nested_project/python/nested_package/_core.pyi\n",
    ):
        repository_root, log_path, pyproject_path, changed_files_path = (
            _nested_inputs(tmp_path / changed.replace("/", "_"), changed)
        )
        assert gate.classify_pytest_inputs(
            log_path=log_path,
            pyproject_path=pyproject_path,
            changed_files_path=changed_files_path,
            repo_root_path=repository_root,
        ) is None


def test_repo_root_must_contain_the_pyproject(tmp_path: Path) -> None:
    """A mismatched or unsafe repository root cannot classify a failure."""

    repository_root, log_path, pyproject_path, changed_files_path = _nested_inputs(
        tmp_path,
        "services/nested_project/python/nested_package/reporting.py\n",
    )
    outside_root = tmp_path / "outside_root"
    outside_root.mkdir()

    assert gate.classify_pytest_inputs(
        log_path=log_path,
        pyproject_path=pyproject_path,
        changed_files_path=changed_files_path,
        repo_root_path=outside_root,
    ) is None

    missing_root = tmp_path / "missing_root"
    assert gate.classify_pytest_inputs(
        log_path=log_path,
        pyproject_path=pyproject_path,
        changed_files_path=changed_files_path,
        repo_root_path=missing_root,
    ) is None

    root_link = tmp_path / "repository_link"
    root_link.symlink_to(repository_root, target_is_directory=True)
    assert gate.classify_pytest_inputs(
        log_path=log_path,
        pyproject_path=pyproject_path,
        changed_files_path=changed_files_path,
        repo_root_path=root_link,
    ) is None


def test_classifier_requires_the_canonical_pyproject_filename(tmp_path: Path) -> None:
    """A differently named TOML file cannot define repository trust paths."""

    repository_root, log_path, pyproject_path, changed_files_path = _nested_inputs(
        tmp_path,
        "services/nested_project/python/nested_package/reporting.py\n",
    )
    renamed = pyproject_path.with_name("project.toml")
    pyproject_path.rename(renamed)

    assert gate.classify_pytest_inputs(
        log_path=log_path,
        pyproject_path=renamed,
        changed_files_path=changed_files_path,
        repo_root_path=repository_root,
    ) is None


def test_root_project_default_python_source_is_repo_relative(tmp_path: Path) -> None:
    """The maturin default source directory remains rooted at the repository."""

    repository_root = tmp_path / "repository_root"
    pyproject = _PYPROJECT.replace('python-source = "python"\n', "").replace(
        'manifest-path = "crates/native_bridge/Cargo.toml"',
        'manifest-path = "Cargo.toml"',
    )
    log_path = _write(repository_root / "pytest.log", _PYTEST_LOG)
    pyproject_path = _write(repository_root / "pyproject.toml", pyproject)
    changed_files_path = _write(
        repository_root / "changed-files.txt",
        "nested_package/reporting.py\n",
    )

    assert gate.classify_pytest_inputs(
        log_path=log_path,
        pyproject_path=pyproject_path,
        changed_files_path=changed_files_path,
        repo_root_path=repository_root,
    ) == "nested_package._core"
