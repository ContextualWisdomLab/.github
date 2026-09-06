"""Tests for the bounded PyO3 native-extension peer gate."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path, PurePosixPath

import pytest

from scripts.ci import python_native_extension_peer_gate as gate


PYPROJECT = """\
[build-system]
requires = ["maturin>=1.10,<2.0"]
build-backend = "maturin"

[tool.maturin]
bindings = "pyo3"
manifest-path = "crates/fast-mlsirm-py/Cargo.toml"
module-name = "fast_mlsirm._core"
python-source = "python"
"""

LOG = """\
============================= test session starts ==============================
collected 0 items / 2 errors

_____________ ERROR collecting tests/test_cov_f_fit.py ______________
ImportError while importing test module '/work/tests/test_cov_f_fit.py'.
Traceback:
/usr/lib/python3/importlib/__init__.py:126: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
tests/test_cov_f_fit.py:4: in <module>
    from fast_mlsirm._core import neg_loglik_and_grad
E   ModuleNotFoundError: No module named 'fast_mlsirm._core'
_____________ ERROR collecting tests/test_mle.py ______________
ImportError while importing test module '/work/tests/test_mle.py'.
Traceback:
tests/test_mle.py:3: in <module>
    import fast_mlsirm._core
E   ModuleNotFoundError: No module named "fast_mlsirm._core"
!!!!!!!!!!!!!!!!!!! Interrupted: 2 errors during collection !!!!!!!!!!!!!!!!!!!!
============================== 2 errors in 0.42s ===============================
"""

PARTIAL_NATIVE_IMPORT_LOG = """\
============================= test session starts ==============================
collected 0 items / 2 errors

_____________ ERROR collecting tests/test_marginal_parity.py ______________
ImportError while importing test module '/work/tests/test_marginal_parity.py'.
Traceback:
/usr/lib/python3/importlib/__init__.py:126: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
tests/test_marginal_parity.py:13: in <module>
    from fast_mlsirm.config import FitConfig
python/fast_mlsirm/interaction_map.py:10: in <module>
    from . import _core
E   ImportError: cannot import name '_core' from partially initialized module 'fast_mlsirm' (most likely due to a circular import) (/work/python/fast_mlsirm/__init__.py)
_____________ ERROR collecting tests/test_mle.py ______________
ImportError while importing test module '/work/tests/test_mle.py'.
Traceback:
tests/test_mle.py:3: in <module>
    import fast_mlsirm._core
python/fast_mlsirm/interaction_map.py:10: in <module>
    from . import _core
E   ImportError: cannot import name '_core' from partially initialized module 'fast_mlsirm' (most likely due to a circular import) (/work/python/fast_mlsirm/__init__.py)
!!!!!!!!!!!!!!!!!!! Interrupted: 2 errors during collection !!!!!!!!!!!!!!!!!!!!
============================== 2 errors in 0.42s ===============================
"""


def write(path: Path, text: str) -> Path:
    """Write UTF-8 fixture text and return its path."""

    path.write_text(text, encoding="utf-8")
    return path


def valid_inputs(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Create one valid log, pyproject, and changed-file fixture."""

    return (
        write(tmp_path / "pytest.log", LOG),
        write(tmp_path / "pyproject.toml", PYPROJECT),
        write(
            tmp_path / "changed.txt",
            "python/fast_mlsirm/scoring/reporting.py\n"
            "tests/test_scoring_reporting.py\n",
        ),
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("src/lib.rs", "src/lib.rs"),
        ("", None),
        ("../src/lib.rs", None),
        ("/src/lib.rs", None),
        ("src\\lib.rs", None),
        ("src/\x00lib.rs", None),
        ("./src/lib.rs", None),
    ],
)
def test_safe_relative_path(raw: str, expected: str | None) -> None:
    """Repository paths reject traversal, aliases, separators, and NUL."""

    result = gate._safe_relative_path(raw)
    assert (result.as_posix() if result is not None else None) == expected


def test_bounded_reader_rejects_missing_directory_symlink_large_and_oserror(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only bounded regular files are accepted."""

    missing = tmp_path / "missing"
    directory = tmp_path / "directory"
    directory.mkdir()
    target = write(tmp_path / "target", "ok")
    symlink = tmp_path / "link"
    symlink.symlink_to(target)
    large = write(tmp_path / "large", "abcd")

    assert gate._read_bounded_regular(missing, 10) is None
    assert gate._read_bounded_regular(directory, 10) is None
    assert gate._read_bounded_regular(symlink, 10) is None
    assert gate._read_bounded_regular(large, 3) is None
    assert gate._read_bounded_regular(target, 10) == b"ok"
    assert gate._read_bounded_regular(target, -1) is None

    monkeypatch.setattr(
        os,
        "open",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError()),
    )
    assert gate._read_bounded_regular(target, 10) is None


def test_bounded_reader_rejects_a_read_that_exceeds_the_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A read that exceeds the declared byte budget fails closed."""
    target = write(tmp_path / "target", "ok")
    original_read = os.read

    def oversized_read(file_descriptor: int, count: int) -> bytes:
        """Return one oversized chunk, then preserve normal descriptor reads."""
        if count > 0:
            monkeypatch.setattr(os, "read", original_read)
            return b"x" * (count + 1)
        return original_read(file_descriptor, count)

    monkeypatch.setattr(os, "read", oversized_read)
    assert gate._read_bounded_regular(target, 2) is None


def test_native_absence_path_rejects_symlink_and_oserror(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Absence evidence never crosses a symlink or hides filesystem errors."""

    target = write(tmp_path / "target", "ok")
    symlink = tmp_path / "link"
    symlink.symlink_to(target)
    assert gate._safe_absent_path(symlink) is False
    monkeypatch.setattr(
        os,
        "lstat",
        lambda _path: (_ for _ in ()).throw(OSError("unavailable")),
    )
    assert gate._safe_absent_path(tmp_path / "missing") is False


def test_read_text_rejects_non_utf8(tmp_path: Path) -> None:
    """Malformed UTF-8 cannot influence classification."""

    path = tmp_path / "bad"
    path.write_bytes(b"\xff")
    assert gate._read_text(path, 10) is None


@pytest.mark.parametrize(
    "replacement",
    [
        'build-backend = "setuptools.build_meta"',
        'bindings = "cffi"',
        'module-name = "not_dotted"',
        'manifest-path = "../Cargo.toml"',
        'manifest-path = "Cargo.lock"',
    ],
)
def test_maturin_contract_rejects_invalid_contracts(
    tmp_path: Path, replacement: str
) -> None:
    """The classifier requires explicit safe maturin/PyO3 metadata."""

    content = PYPROJECT
    if replacement.startswith("build-backend"):
        content = content.replace('build-backend = "maturin"', replacement)
    elif replacement.startswith("bindings"):
        content = content.replace('bindings = "pyo3"', replacement)
    elif replacement.startswith("module-name"):
        content = content.replace('module-name = "fast_mlsirm._core"', replacement)
    else:
        content = content.replace(
            'manifest-path = "crates/fast-mlsirm-py/Cargo.toml"', replacement
        )
    assert gate._maturin_contract(write(tmp_path / "pyproject.toml", content)) is None


@pytest.mark.parametrize(
    "content",
    [
        "",
        "not = [valid",
        "[build-system]\nbuild-backend = \"maturin\"\n",
        "[tool]\nvalue = 1\n",
        "[tool.maturin]\nbindings = \"pyo3\"\nmodule-name = \"a.b\"\n",
        "[build-system]\nbuild-backend = \"maturin\"\n[tool]\nmaturin = 1\n",
        (
            "[build-system]\nbuild-backend = \"maturin\"\n"
            "[tool.maturin]\nbindings = \"pyo3\"\nmodule-name = 3\n"
        ),
    ],
)
def test_maturin_contract_rejects_malformed_metadata(
    tmp_path: Path, content: str
) -> None:
    """Missing and malformed TOML structures fail closed."""

    assert gate._maturin_contract(write(tmp_path / "pyproject.toml", content)) is None


def test_maturin_contract_uses_default_manifest(tmp_path: Path) -> None:
    """A safe root Cargo manifest is the maturin default."""

    content = PYPROJECT.replace(
        'manifest-path = "crates/fast-mlsirm-py/Cargo.toml"\n', ""
    )
    assert gate._maturin_contract(write(tmp_path / "pyproject.toml", content)) == (
        "fast_mlsirm._core",
        PurePosixPath("Cargo.toml"),
        PurePosixPath("python"),
    )


def test_native_absence_evidence_enables_only_sealed_partial_imports(
    tmp_path: Path,
) -> None:
    """Partial imports require an exact pre-test absence record."""

    log = write(tmp_path / "pytest.log", PARTIAL_NATIVE_IMPORT_LOG)
    pyproject = write(tmp_path / "pyproject.toml", PYPROJECT)
    changed = write(tmp_path / "changed.txt", "tests/test_mle.py\n")
    evidence = write(
        tmp_path / "absence.txt",
        gate.native_module_absence_evidence(pyproject_path=pyproject) or "",
    )

    assert gate.classify_pytest_inputs(
        log_path=log,
        pyproject_path=pyproject,
        changed_files_path=changed,
        native_module_absence_evidence=evidence,
    ) == "fast_mlsirm._core"
    evidence.write_text("native-module-absent:other._core\n", encoding="utf-8")
    assert gate.classify_pytest_inputs(
        log_path=log,
        pyproject_path=pyproject,
        changed_files_path=changed,
        native_module_absence_evidence=evidence,
    ) is None


def test_native_absence_evidence_rejects_materialized_extension(
    tmp_path: Path,
) -> None:
    """A materialized extension prevents sealed absence evidence."""

    pyproject = write(tmp_path / "pyproject.toml", PYPROJECT)
    extension = tmp_path / "python/fast_mlsirm/_core"
    extension.parent.mkdir(parents=True)
    write(extension.with_name(extension.name + gate.EXTENSION_SUFFIXES[0]), "native")

    assert gate.native_module_absence_evidence(pyproject_path=pyproject) is None


def test_native_absence_evidence_rejects_invalid_repository_context(
    tmp_path: Path,
) -> None:
    """Sealing fails when metadata or repository anchoring is invalid."""

    pyproject = write(tmp_path / "pyproject.toml", PYPROJECT)
    assert (
        gate.native_module_absence_evidence(
            pyproject_path=tmp_path / "missing.toml",
        )
        is None
    )
    assert (
        gate.native_module_absence_evidence(
            pyproject_path=pyproject,
            logical_pyproject_path=Path("pyproject.toml"),
        )
        is None
    )
    repository_file = write(tmp_path / "repository-file", "not a directory")
    assert (
        gate.native_module_absence_evidence(
            pyproject_path=pyproject,
            repo_root_path=repository_file,
        )
        is None
    )


def test_native_absence_evidence_rejects_resolution_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A repository resolution error fails closed after path validation."""

    pyproject = write(tmp_path / "pyproject.toml", PYPROJECT)
    original_resolve = Path.resolve
    resolve_calls = 0

    def fail_second_resolve(path: Path, *args, **kwargs):
        """Fail only while sealing the already validated repository root."""

        nonlocal resolve_calls
        if path == tmp_path:
            resolve_calls += 1
            if resolve_calls == 3:
                raise OSError("unavailable")
        return original_resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", fail_second_resolve)
    assert gate.native_module_absence_evidence(pyproject_path=pyproject) is None


def test_native_absence_evidence_rejects_repository_that_changes_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A repository root that stops being a directory fails closed."""

    pyproject = write(tmp_path / "pyproject.toml", PYPROJECT)
    original_is_dir = Path.is_dir
    is_dir_calls = 0

    def false_second_is_dir(path: Path, *args, **kwargs):
        """Fail the second root-directory check during sealing."""

        nonlocal is_dir_calls
        if path == tmp_path:
            is_dir_calls += 1
            if is_dir_calls == 2:
                return False
        return original_is_dir(path, *args, **kwargs)

    monkeypatch.setattr(Path, "is_dir", false_second_is_dir)
    assert gate.native_module_absence_evidence(pyproject_path=pyproject) is None


@pytest.mark.parametrize(
    "changed",
    [
        "pyproject.toml\n",
        "Cargo.toml\n",
        "Cargo.lock\n",
        "src/lib.rs\n",
        "build.rs\n",
        "setup.py\n",
        "requirements-ci.txt\n",
        "requirements-ci.in\n",
        "constraints.txt\n",
        ".github/workflows/ci.yml\n",
        ".github/actions/setup/action.yml\n",
        "python/fast_mlsirm/_core.pyi\n",
        "python/fast_mlsirm/scoring/reporting.py\n",
        "crates/fast-mlsirm-py/README.md\n",
        "nested/pyproject.toml\n",
        "uv.lock\n",
    ],
)
def test_native_trust_boundary_changes_block_deferral(
    tmp_path: Path, changed: str
) -> None:
    """Native, packaging, dependency, and CI changes require direct builds."""

    log, pyproject, changed_path = valid_inputs(tmp_path)
    changed_path.write_text(changed, encoding="utf-8")
    assert gate.classify_pytest_inputs(
        log_path=log,
        pyproject_path=pyproject,
        changed_files_path=changed_path,
    ) is None


def test_documentation_under_requirements_directory_does_not_block_deferral(
    tmp_path: Path,
) -> None:
    """A prose file in docs/requirements/ is not a lock or packaging change."""

    log, pyproject, changed_path = valid_inputs(tmp_path)
    changed_path.write_text("docs/requirements/overview.md\n", encoding="utf-8")
    assert (
        gate.classify_pytest_inputs(
            log_path=log,
            pyproject_path=pyproject,
            changed_files_path=changed_path,
        )
        == "fast_mlsirm._core"
    )
    changed_path.write_text("docs/requirements/pins.txt\n", encoding="utf-8")
    assert (
        gate.classify_pytest_inputs(
            log_path=log,
            pyproject_path=pyproject,
            changed_files_path=changed_path,
        )
        is None
    )


@pytest.mark.parametrize(
    "changed",
    [
        "../bad.py\n",
        "same.py\nsame.py\n",
        "C:\\bad.py\n",
    ],
)
def test_changed_file_list_rejects_unsafe_entries(
    tmp_path: Path, changed: str
) -> None:
    """Untrusted path lists reject traversal, duplicates, and platform aliases."""

    path = write(tmp_path / "changed.txt", changed)
    assert gate._read_changed_files(path) is None


def test_changed_file_list_ignores_blank_lines(tmp_path: Path) -> None:
    """Blank lines do not create path aliases."""

    path = write(tmp_path / "changed.txt", "\npython/pkg.py\n\n")
    assert gate._read_changed_files(path) == (Path("python/pkg.py"),)


@pytest.mark.parametrize(
    "log",
    [
        "",
        LOG.replace("fast_mlsirm._core", "other_module", 1),
        LOG.replace("Interrupted: 2 errors", "Interrupted: 1 error"),
        LOG.replace("Interrupted: 2 errors", "Interrupted: 2 errors") + "\nFAILED x.py::test_x\n",
        LOG + "\n=== FAILURES ===\n",
        LOG + "\nINTERNALERROR> boom\n",
        LOG + "\nFatal Python error\n",
        LOG + "\nSegmentation fault\n",
        LOG + "\nERROR at setup\n",
        LOG + "\nERROR at teardown\n",
        LOG.replace(
            "E   ModuleNotFoundError: No module named 'fast_mlsirm._core'",
            "E   ImportError: bad import",
            1,
        ),
        LOG.replace(
            "_____________ ERROR collecting tests/test_mle.py ______________\n", ""
        ),
        LOG.replace(
            'E   ModuleNotFoundError: No module named "fast_mlsirm._core"\n', ""
        ),
        LOG.replace("Interrupted: 2 errors during collection", "no interruption"),
        LOG + "\n output truncated: 999 lines\n",
    ],
)
def test_pytest_classifier_rejects_ambiguous_or_mixed_failures(log: str) -> None:
    """Only complete, exclusive declared-module collection failures defer."""

    assert not gate.classify_pytest_failure(
        log,
        module_name="fast_mlsirm._core",
    )


def test_pytest_classifier_accepts_exact_missing_extension() -> None:
    """A complete exact-module collection failure is classifiable."""

    assert gate.classify_pytest_failure(
        LOG,
        module_name="fast_mlsirm._core",
    )


def test_pytest_classifier_accepts_exact_partial_native_import() -> None:
    """A PyO3 circular-import failure needs sealed absence evidence."""

    assert gate.classify_pytest_failure(
        PARTIAL_NATIVE_IMPORT_LOG,
        module_name="fast_mlsirm._core",
        native_module_absent=True,
    )


def test_pytest_classifier_rejects_partial_native_import_without_absence_evidence() -> None:
    """A partial-import message alone cannot prove that the extension is absent."""

    assert not gate.classify_pytest_failure(
        PARTIAL_NATIVE_IMPORT_LOG,
        module_name="fast_mlsirm._core",
    )


def test_pytest_classifier_rejects_mixed_native_import_failure() -> None:
    """A native-import failure mixed with another category remains blocking."""

    log = PARTIAL_NATIVE_IMPORT_LOG.replace(
        "E   ImportError: cannot import name '_core'",
        "E   ModuleNotFoundError: No module named 'fast_mlsirm._core'",
        1,
    )
    assert not gate.classify_pytest_failure(
        log,
        module_name="fast_mlsirm._core",
    )


def test_pytest_classifier_rejects_incomplete_partial_native_import_failure() -> None:
    """Every collection error must carry the exact native-import exception."""

    log = PARTIAL_NATIVE_IMPORT_LOG.replace(
        "E   ImportError: cannot import name '_core'", "", 1
    )
    assert not gate.classify_pytest_failure(
        log,
        module_name="fast_mlsirm._core",
        native_module_absent=True,
    )


def test_pytest_classifier_rejects_undotted_partial_native_module() -> None:
    """A partial-import exception cannot bind to an undotted module name."""

    assert not gate.classify_pytest_failure(
        PARTIAL_NATIVE_IMPORT_LOG,
        module_name="_core",
        native_module_absent=True,
    )


@pytest.mark.parametrize(
    "replacement",
    [
        ("fast_mlsirm' (most likely", "other_package' (most likely"),
        ("cannot import name '_core'", "cannot import name 'other'"),
        ("from . import _core", "from . import other"),
    ],
)
def test_pytest_classifier_rejects_mismatched_partial_native_import(
    replacement: tuple[str, str],
) -> None:
    """A circular import from another package or symbol remains blocking."""

    log = PARTIAL_NATIVE_IMPORT_LOG.replace(*replacement)
    assert not gate.classify_pytest_failure(
        log,
        module_name="fast_mlsirm._core",
        native_module_absent=True,
    )


def test_pytest_classifier_rejects_partial_import_without_direct_native_import() -> None:
    """A partial exception without a direct native import remains ambiguous."""

    log = PARTIAL_NATIVE_IMPORT_LOG.replace(
        "    import fast_mlsirm._core\n", "", 1
    ).replace("    from . import _core\n", "")
    assert not gate.classify_pytest_failure(
        log,
        module_name="fast_mlsirm._core",
        native_module_absent=True,
    )


def test_classify_inputs_accepts_python_only_change(tmp_path: Path) -> None:
    """Python-only changes may defer to trusted native peer evidence."""

    log, pyproject, changed = valid_inputs(tmp_path)
    changed.write_text("tests/test_scoring_reporting.py\n", encoding="utf-8")
    assert gate.classify_pytest_inputs(
        log_path=log,
        pyproject_path=pyproject,
        changed_files_path=changed,
    ) == "fast_mlsirm._core"


def test_classify_inputs_rejects_python_source_change(tmp_path: Path) -> None:
    """Changes below the declared Python source root require direct testing."""

    log, pyproject, changed = valid_inputs(tmp_path)
    changed.write_text("python/fast_mlsirm/scoring/reporting.py\n", encoding="utf-8")
    assert gate.classify_pytest_inputs(
        log_path=log,
        pyproject_path=pyproject,
        changed_files_path=changed,
    ) is None


def test_classify_inputs_separates_sealed_metadata_from_logical_path(
    tmp_path: Path,
) -> None:
    """A sealed TOML copy retains its independently validated repository path."""

    repository = tmp_path / "repository"
    repository.mkdir()
    log = write(tmp_path / "pytest.log", LOG)
    snapshot = write(tmp_path / "sealed-metadata", PYPROJECT)
    changed = write(
        tmp_path / "changed.txt",
        "tests/test_scoring_reporting.py\n",
    )

    assert gate.classify_pytest_inputs(
        log_path=log,
        pyproject_path=snapshot,
        logical_pyproject_path=Path("pyproject.toml"),
        changed_files_path=changed,
        repo_root_path=repository,
    ) == "fast_mlsirm._core"


@pytest.mark.parametrize(
    "logical_pyproject",
    [Path("../pyproject.toml"), Path("project.toml")],
)
def test_classify_inputs_rejects_unsafe_logical_metadata_paths(
    tmp_path: Path,
    logical_pyproject: Path,
) -> None:
    """Logical paths must be traversal-free canonical repository metadata."""

    repository = tmp_path / "repository"
    repository.mkdir()
    log, snapshot, changed = valid_inputs(tmp_path)

    assert gate.classify_pytest_inputs(
        log_path=log,
        pyproject_path=snapshot,
        logical_pyproject_path=logical_pyproject,
        changed_files_path=changed,
        repo_root_path=repository,
    ) is None


def test_classify_inputs_requires_repo_root_for_a_logical_path(
    tmp_path: Path,
) -> None:
    """A logical location without an anchoring repository cannot defer."""

    log, snapshot, changed = valid_inputs(tmp_path)
    assert gate.classify_pytest_inputs(
        log_path=log,
        pyproject_path=snapshot,
        logical_pyproject_path=Path("pyproject.toml"),
        changed_files_path=changed,
    ) is None


def test_classify_inputs_rejects_unsafe_input_files(tmp_path: Path) -> None:
    """Missing or malformed inputs block classification."""

    log, pyproject, changed = valid_inputs(tmp_path)
    log.unlink()
    assert gate.classify_pytest_inputs(
        log_path=log,
        pyproject_path=pyproject,
        changed_files_path=changed,
    ) is None


def test_workflow_name_supports_flat_and_nested_records() -> None:
    """Check records normalize trusted flat and GraphQL workflow names."""

    assert gate._workflow_name({"workflow": "CI"}) == "CI"
    assert gate._workflow_name({}) is None
    assert gate._workflow_name({"checkSuite": 1}) is None
    assert gate._workflow_name({"checkSuite": {"workflowRun": 1}}) is None
    assert gate._workflow_name(
        {"checkSuite": {"workflowRun": {"workflow": 1}}}
    ) is None
    assert gate._workflow_name(
        {"checkSuite": {"workflowRun": {"workflow": {"name": 1}}}}
    ) is None
    assert gate._workflow_name(
        {"checkSuite": {"workflowRun": {"workflow": {"name": "CI"}}}}
    ) == "CI"


def successful_checks(head: str) -> list[dict[str, object]]:
    """Return exact-head Python, Rust, and package check runs."""

    return [
        {
            "__typename": "CheckRun",
            "workflow": "CI",
            "name": name,
            "head_sha": head,
            "status": "COMPLETED",
            "conclusion": "SUCCESS",
        }
        for name in ("python", "rust", "package")
    ]


@pytest.mark.parametrize(
    "mutation",
    [
        lambda checks: checks.pop(),
        lambda checks: checks[0].update(head_sha="b" * 40),
        lambda checks: checks[0].update(status="IN_PROGRESS"),
        lambda checks: checks[0].update(conclusion="FAILURE"),
        lambda checks: checks[0].update(__typename="StatusContext"),
        lambda checks: checks[0].update(workflow="Other"),
        lambda checks: checks[0].update(name="Python"),
    ],
)
def test_exact_head_checks_reject_missing_stale_pending_or_spoofed(
    mutation,
) -> None:
    """Every required exact-head CheckRun must complete successfully."""

    head = "a" * 40
    checks = successful_checks(head)
    mutation(checks)
    assert not gate.has_required_exact_head_checks(
        checks,
        head_sha=head,
        required_checks=(
            ("CI", "python"),
            ("CI", "rust"),
            ("CI", "package"),
        ),
    )


def test_exact_head_checks_accept_nested_workflow_records() -> None:
    """GraphQL-shaped workflow names remain acceptable after normalization."""

    head = "a" * 40
    checks = successful_checks(head)
    checks[0].pop("workflow")
    checks[0]["checkSuite"] = {
        "workflowRun": {"workflow": {"name": "CI"}}
    }
    assert gate.has_required_exact_head_checks(
        checks,
        head_sha=head,
        required_checks=(
            ("CI", "python"),
            ("CI", "rust"),
            ("CI", "package"),
        ),
    )


@pytest.mark.parametrize(
    ("head", "required"),
    [
        ("bad", (("CI", "python"),)),
        ("a" * 40, ()),
        ("a" * 40, (("CI", "python"), ("CI", "python"))),
    ],
)
def test_exact_head_checks_reject_invalid_contract(
    head: str, required: tuple[tuple[str, str], ...]
) -> None:
    """Malformed SHAs and duplicate or empty requirements fail closed."""

    assert not gate.has_required_exact_head_checks(
        successful_checks("a" * 40),
        head_sha=head,
        required_checks=required,
    )


def test_read_checks_rejects_unsafe_or_invalid_json(tmp_path: Path) -> None:
    """Peer evidence must be a bounded JSON list of objects."""

    assert gate._read_checks(write(tmp_path / "bad.json", "{")) is None
    assert gate._read_checks(write(tmp_path / "scalar.json", "{}")) is None
    assert gate._read_checks(write(tmp_path / "mixed.json", "[1]")) is None
    valid = write(tmp_path / "valid.json", '[{"name":"python"}]')
    assert gate._read_checks(valid) == [{"name": "python"}]


@pytest.mark.parametrize(
    "value",
    ["CI::python", " CI :: python "],
)
def test_parse_required_check(value: str) -> None:
    """Trusted check specifications use exact workflow and job names."""

    assert gate._parse_required_check(value) == ("CI", "python")


@pytest.mark.parametrize("value", ["CI", "::python", "CI::"])
def test_parse_required_check_rejects_malformed(value: str) -> None:
    """Empty or delimiter-free check specifications are rejected."""

    with pytest.raises(argparse.ArgumentTypeError):
        gate._parse_required_check(value)


def test_maturin_contract_rejects_unsafe_file(tmp_path: Path) -> None:
    """Missing project metadata cannot define a native peer contract."""

    assert gate._maturin_contract(tmp_path / "missing.toml") is None


def test_changed_file_reader_rejects_missing_file(tmp_path: Path) -> None:
    """Missing changed-file evidence blocks deferral."""

    assert gate._read_changed_files(tmp_path / "missing.txt") is None


def test_classify_inputs_rejects_resolve_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Filesystem resolution failures do not produce a deferral."""

    log, pyproject, changed = valid_inputs(tmp_path)
    original = Path.resolve

    def fail_pyproject(path: Path, *args, **kwargs):
        """Raise only while the classifier resolves the project file."""

        if path == pyproject:
            raise OSError("unavailable")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", fail_pyproject)
    assert gate.classify_pytest_inputs(
        log_path=log,
        pyproject_path=pyproject,
        changed_files_path=changed,
    ) is None


def test_classify_inputs_rejects_nonmatching_log(tmp_path: Path) -> None:
    """Valid metadata cannot defer an unrelated pytest failure."""

    log, pyproject, changed = valid_inputs(tmp_path)
    log.write_text("FAILED tests/test_x.py::test_x\n", encoding="utf-8")
    assert gate.classify_pytest_inputs(
        log_path=log,
        pyproject_path=pyproject,
        changed_files_path=changed,
    ) is None


def test_read_checks_rejects_missing_file(tmp_path: Path) -> None:
    """Missing peer-check evidence blocks approval."""

    assert gate._read_checks(tmp_path / "missing.json") is None


def test_cli_classify_and_require_checks(tmp_path: Path, capsys) -> None:
    """Both CLI operations emit explicit success and fail-closed diagnostics."""

    log, pyproject, changed = valid_inputs(tmp_path)
    assert gate.main(
        ["seal-native-absence", "--pyproject", str(tmp_path / "missing.toml")]
    ) == 1
    assert "could not be sealed" in capsys.readouterr().err
    changed.write_text("tests/test_scoring_reporting.py\n", encoding="utf-8")
    assert gate.main(
        [
            "seal-native-absence",
            "--pyproject",
            str(pyproject),
        ]
    ) == 0
    assert capsys.readouterr().out == "native-module-absent:fast_mlsirm._core\n"
    assert gate.main(
        [
            "classify-pytest",
            "--log",
            str(log),
            "--pyproject",
            str(pyproject),
            "--changed-files",
            str(changed),
        ]
    ) == 0
    assert "unchanged declared native module" in capsys.readouterr().out

    changed.write_text("Cargo.toml\n", encoding="utf-8")
    assert gate.main(
        [
            "classify-pytest",
            "--log",
            str(log),
            "--pyproject",
            str(pyproject),
            "--changed-files",
            str(changed),
        ]
    ) == 1
    assert "not safely deferrable" in capsys.readouterr().err

    head = "a" * 40
    checks_path = write(
        tmp_path / "checks.json",
        json.dumps(successful_checks(head)),
    )
    assert gate.main(
        [
            "require-checks",
            "--checks-json",
            str(checks_path),
            "--head-sha",
            head,
            "--required-check",
            "CI::python",
            "--required-check",
            "CI::rust",
            "--required-check",
            "CI::package",
        ]
    ) == 0
    assert "all required exact-head" in capsys.readouterr().out

    checks_path.write_text("[]", encoding="utf-8")
    assert gate.main(
        [
            "require-checks",
            "--checks-json",
            str(checks_path),
            "--head-sha",
            head,
            "--required-check",
            "CI::python",
        ]
    ) == 1
    assert "not proven" in capsys.readouterr().err
