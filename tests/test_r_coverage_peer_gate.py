"""Tests for fail-closed R coverage deferral and peer-check evidence."""

from __future__ import annotations

import json
from pathlib import Path
import runpy
import sys

import pytest

from scripts.ci import r_coverage_peer_gate as gate


def test_classifies_only_own_package_not_found_failures() -> None:
    """Every reported failure must be packageNotFoundError for the package under test."""
    text = """\
Error ('test-one.R:1:1'): first
<packageNotFoundError/error/condition>
Error in `loadNamespace(x)`: there is no package called 'aFIPC'
Error ('test-two.R:2:1'): second
<packageNotFoundError/error/condition>
Error in `loadNamespace(x)`: there is no package called 'aFIPC'
[ FAIL 2 | WARN 0 | SKIP 1 | PASS 3 ]
Error: Test failures
"""
    assert gate.classify_testthat_failure(text, "aFIPC")


def test_rejects_invalid_or_mixed_test_failures() -> None:
    """Malformed names, assertions, other packages, and count drift fail closed."""
    assertion = "[ FAIL 1 | WARN 0 | SKIP 0 | PASS 0 ]\nError: Test failures\n"
    other_package = """\
Error ('test-one.R:1:1'): first
<packageNotFoundError/error/condition>
Error in `loadNamespace(x)`: there is no package called 'mirt'
[ FAIL 1 | WARN 0 | SKIP 0 | PASS 0 ]
Error: Test failures
"""
    mismatched = other_package.replace("FAIL 1", "FAIL 2").replace("mirt", "aFIPC")
    zero_failures = "[ FAIL 0 | WARN 0 | SKIP 0 | PASS 1 ]\nError: Test failures\n"

    assert not gate.classify_testthat_failure("", "aFIPC")
    assert not gate.classify_testthat_failure(
        "[ FAIL 1 | WARN 0 | SKIP 0 | PASS 0 ]", "aFIPC"
    )
    assert not gate.classify_testthat_failure(zero_failures, "aFIPC")
    assert not gate.classify_testthat_failure(assertion, "aFIPC")
    assert not gate.classify_testthat_failure(other_package, "aFIPC")
    assert not gate.classify_testthat_failure(mismatched, "aFIPC")
    assert not gate.classify_testthat_failure(other_package, "../aFIPC")
    assert not gate.classify_testthat_failure(
        other_package,
        "aFIPC",
        allowed_missing={"../mirt"},
    )


def test_allows_only_declared_suggests_package_failures() -> None:
    """A peer-check deferral may include packageNotFound errors for declared Suggests."""
    text = """\
Error ('test-one.R:1:1'): first
<packageNotFoundError/error/condition>
Error in `loadNamespace(x)`: there is no package called 'aFIPC'
Error ('test-two.R:2:1'): second
<packageNotFoundError/error/condition>
Error in `loadNamespace(x)`: there is no package called 'mockery'
[ FAIL 2 | WARN 0 | SKIP 0 | PASS 0 ]
Error: Test failures
"""
    description = """\
Package: aFIPC
Suggests:
    mockery,
    testthat (>= 3.0.0)
"""
    suggests = gate.declared_suggests(description)

    assert suggests == {"mockery", "testthat"}
    assert not gate.classify_testthat_failure(text, "aFIPC")
    assert gate.classify_testthat_failure(
        text,
        "aFIPC",
        allowed_missing=suggests,
    )
    assert not gate.classify_testthat_failure(
        text.replace("mockery", "undeclared"),
        "aFIPC",
        allowed_missing=suggests,
    )


@pytest.mark.parametrize(
    ("description", "expected"),
    [
        ("Package: pkg\n", set()),
        ("Package: pkg\nSuggests:\n", set()),
        ("invalid preamble\nSuggests: helper\n", {"helper"}),
        ("Package: pkg\nSuggests: helper (>= 1.2), other.pkg\n", {"helper", "other.pkg"}),
        ("Package: pkg\nSuggests: helper (\n", None),
        ("Package: pkg\nSuggests: helper\ninvalid continuation\n", None),
        ("Package: pkg\nSuggests: helper\nSuggests: other\n", None),
    ],
)
def test_parses_description_suggests_fail_closed(
    description: str, expected: set[str] | None
) -> None:
    """Malformed or duplicate Suggests fields cannot broaden the deferral set."""
    assert gate.declared_suggests(description) == expected


def test_requires_successful_r_cmd_check_workflow() -> None:
    """Only a successful check whose workflow/name identifies R CMD check qualifies."""
    checks = [
        {"workflow": "R CMD check", "name": "check", "state": "SUCCESS"},
        {"workflow": "Other", "name": "test", "state": "FAILURE"},
    ]
    assert gate.has_successful_r_cmd_check(checks)
    assert gate.has_successful_r_cmd_check(
        [{"workflow": "", "name": "R-CMD-check", "state": "success"}]
    )
    assert not gate.has_successful_r_cmd_check(
        [{"workflow": "R CMD check", "name": "check", "state": "FAILURE"}]
    )
    assert not gate.has_successful_r_cmd_check(
        [{"workflow": "CI", "name": "tests", "state": "SUCCESS"}]
    )
    assert not gate.has_successful_r_cmd_check({"checks": checks})
    assert not gate.has_successful_r_cmd_check(["invalid"])


def test_cli_classifies_log_and_check_json(tmp_path: Path, capsys) -> None:
    """Both CLI modes accept bounded valid evidence and reject invalid JSON."""
    log = tmp_path / "testthat.log"
    log.write_text(
        "Error ('x.R:1:1'): x\n"
        "<packageNotFoundError/error/condition>\n"
        "Error in `loadNamespace(x)`: there is no package called 'pkg'\n"
        "Error ('y.R:2:1'): y\n"
        "<packageNotFoundError/error/condition>\n"
        "Error in `loadNamespace(x)`: there is no package called 'helper'\n"
        "[ FAIL 2 | WARN 0 | SKIP 0 | PASS 0 ]\n"
        "Error: Test failures\n",
        encoding="utf-8",
    )
    checks = tmp_path / "checks.json"
    checks.write_text(
        json.dumps([{"workflow": "R CMD check", "name": "check", "state": "SUCCESS"}]),
        encoding="utf-8",
    )
    description = tmp_path / "DESCRIPTION"
    description.write_text("Package: pkg\nSuggests: helper\n", encoding="utf-8")

    assert gate.main(["classify-testthat", "--log", str(log), "--package", "pkg"]) == 1
    assert (
        gate.main(
            [
                "classify-testthat",
                "--log",
                str(log),
                "--package",
                "pkg",
                "--description",
                str(description),
            ]
        )
        == 0
    )
    assert gate.main(["require-check", "--checks-json", str(checks)]) == 0

    checks.write_text("{", encoding="utf-8")
    assert gate.main(["require-check", "--checks-json", str(checks)]) == 1
    assert (
        gate.main(
            [
                "require-check",
                "--checks-json",
                str(tmp_path / "missing-checks.json"),
            ]
        )
        == 1
    )
    assert "not found" in capsys.readouterr().err


def test_cli_rejects_unsafe_or_oversized_logs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Missing, symlinked, and oversized artifacts never authorize deferral."""
    missing = tmp_path / "missing.log"
    assert (
        gate.main(["classify-testthat", "--log", str(missing), "--package", "pkg"])
        == 1
    )

    target = tmp_path / "target.log"
    target.write_text("small", encoding="utf-8")
    link = tmp_path / "link.log"
    link.symlink_to(target)
    assert gate.main(["classify-testthat", "--log", str(link), "--package", "pkg"]) == 1

    target.write_bytes(b"x" * (gate.MAX_LOG_BYTES + 1))
    assert gate.main(["classify-testthat", "--log", str(target), "--package", "pkg"]) == 1

    monkeypatch.setattr(Path, "is_file", lambda _path: (_ for _ in ()).throw(OSError()))
    assert gate._read_bounded_text(target) is None


def test_script_entrypoint_returns_cli_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The executable entrypoint propagates the fail-closed CLI status."""
    missing = tmp_path / "missing.log"
    script = Path("scripts/ci/r_coverage_peer_gate.py")
    monkeypatch.setattr(
        sys,
        "argv",
        [str(script), "classify-testthat", "--log", str(missing), "--package", "pkg"],
    )

    with pytest.raises(SystemExit) as raised:
        runpy.run_path(str(script), run_name="__main__")

    assert raised.value.code == 1
