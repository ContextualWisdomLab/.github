"""Requirements-directory trust-boundary regressions for PyO3 peer evidence."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.ci import python_native_extension_peer_gate as gate


_PYPROJECT = """\
[build-system]
requires = ["maturin>=1.10,<2.0"]
build-backend = "maturin"

[tool.maturin]
bindings = "pyo3"
manifest-path = "crates/fast-mlsirm-py/Cargo.toml"
module-name = "fast_mlsirm._core"
python-source = "python"
"""

_PYTEST_LOG = """\
============================= test session starts ==============================
collected 0 items / 1 error

_____________ ERROR collecting tests/test_mle.py ______________
ImportError while importing test module '/work/tests/test_mle.py'.
Traceback:
tests/test_mle.py:3: in <module>
    import fast_mlsirm._core
E   ModuleNotFoundError: No module named "fast_mlsirm._core"
!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
============================== 1 error in 0.20s ===============================
"""


def _write(path: Path, content: str) -> Path:
    """Write one UTF-8 fixture and return its path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


@pytest.mark.parametrize(
    "changed_path",
    (
        "requirements/ci.txt",
        "requirements/ci.in",
        "requirements/notes.txt",
        "services/scoring_service/requirements/package.txt",
        "services/scoring_service/requirements/package.in",
    ),
)
def test_requirements_directory_changes_block_native_peer_deferral(
    tmp_path: Path,
    changed_path: str,
) -> None:
    """Direct requirements-directory changes require current-head native builds."""
    log_path = _write(tmp_path / "pytest.log", _PYTEST_LOG)
    pyproject_path = _write(tmp_path / "pyproject.toml", _PYPROJECT)
    changed_files_path = _write(tmp_path / "changed-files.txt", changed_path + "\n")

    assert gate.classify_pytest_inputs(
        log_path=log_path,
        pyproject_path=pyproject_path,
        changed_files_path=changed_files_path,
        repo_root_path=tmp_path,
    ) is None


def test_unrelated_txt_outside_requirements_directory_can_still_defer(
    tmp_path: Path,
) -> None:
    """A documentation text file does not become a dependency boundary by suffix."""
    log_path = _write(tmp_path / "pytest.log", _PYTEST_LOG)
    pyproject_path = _write(tmp_path / "pyproject.toml", _PYPROJECT)
    changed_files_path = _write(
        tmp_path / "changed-files.txt",
        "docs/release_notes.txt\n",
    )

    assert gate.classify_pytest_inputs(
        log_path=log_path,
        pyproject_path=pyproject_path,
        changed_files_path=changed_files_path,
        repo_root_path=tmp_path,
    ) == "fast_mlsirm._core"
