"""Tests for the bounded PyO3 native-extension peer gate."""

from __future__ import annotations

import argparse
import json
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

    monkeypatch.setattr(Path, "read_bytes", lambda _self: (_ for _ in ()).throw(OSError()))
    assert gate._read_bounded_regular(target, 10) is None


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


def test_classify_inputs_accepts_python_only_change(tmp_path: Path) -> None:
    """Python-only changes may defer to trusted native peer evidence."""

    log, pyproject, changed = valid_inputs(tmp_path)
    assert gate.classify_pytest_inputs(
        log_path=log,
        pyproject_path=pyproject,
        changed_files_path=changed,
    ) == "fast_mlsirm._core"


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
