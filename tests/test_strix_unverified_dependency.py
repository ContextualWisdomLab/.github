"""Strix findings naming a package the repository does not depend on are unverified.

fast-mlsirm#2246 (run 36580588738) failed its required Strix gate on
"VULN-0001: CVE-2024-1234 in lodash 4.17.20" from the free fallback model. The
repository is Rust and Python with no JavaScript lockfile, and CVE-2024-1234 is
unrelated to lodash. With no file location the gate failed closed as unmapped.
"""

from __future__ import annotations

import runpy
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.ci.strix_unverified_dependency import (
    main,
    named_packages,
    unverified_dependency_finding,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
HELPER = REPO_ROOT / "scripts/ci/strix_unverified_dependency.py"

# Verbatim vuln-0001.md from the strix-reports artifact of run 36580588738.
LODASH_REPORT = """# CVE-2024-1234 in lodash 4.17.20 (prototype pollution)

**ID:** vuln-0001
**Severity:** MEDIUM
**Found:** 2026-09-29 14:22:11 UTC
**Target:** lodash 4.17.20
**Package:** lodash
**Ecosystem:** npm
**Installed Version:** 4.17.20
**Fixed Version:** 4.17.21
**Introduced By:** express@4.18.1
**Dependency Chain:** express@4.18.1 > lodash@4.17.20
**CVE:** CVE-2024-1234
**CWE:** CWE-78
**CVSS:** 5.6
**Fix Effort:** Low

## Description

This report documents the vulnerability CVE-2024-1234 in lodash 4.17.20, which allows for prototype pollution.
"""


def _rust_python_repo(root: Path) -> Path:
    root.mkdir()
    (root / "Cargo.lock").write_text('version = 3\n\n[[package]]\nname = "itoa"\nversion = "1.0.11"\n')
    (root / "uv.lock").write_text('version = 1\n\n[[package]]\nname = "numpy"\nversion = "2.1.0"\n')
    (root / "pyproject.toml").write_text('[project]\nname = "demo"\ndependencies = ["numpy>=2"]\n')
    return root


def test_package_names_come_only_from_structured_fields() -> None:
    assert named_packages(LODASH_REPORT) == {"lodash", "express"}
    assert named_packages("**Target:** lodash@4.17.20\n") == {"lodash"}
    assert named_packages("**Package:** @babel/core\n") == {"@babel/core"}
    assert named_packages("**Target:** crates/core/src/lib.rs:10\n") == set()
    assert named_packages("**Target:** src/app.py\n") == set()
    # The gate console log boxes the same fields (run 36580588738 gate-console.log).
    assert named_packages("│  Target: lodash 4.17.20                                      │\n") == {"lodash"}
    # Free text such as "weak TLS in openssl 1.1.1" never names a package.
    assert named_packages("# Weak TLS in openssl 1.1.1\n\n**Severity:** HIGH\n") == set()


def test_a_named_dependency_present_anywhere_keeps_the_finding(tmp_path: Path) -> None:
    repo = _rust_python_repo(tmp_path / "repo")
    (repo / "package.json").write_text('{"dependencies": {"express": "4.18.1"}}')
    assert not unverified_dependency_finding(LODASH_REPORT, repo)


def test_lodash_claim_on_rust_python_repo_is_unverified(tmp_path: Path) -> None:
    repo = _rust_python_repo(tmp_path / "repo")
    assert unverified_dependency_finding(LODASH_REPORT, repo)


def test_package_present_in_a_lockfile_stays_a_finding(tmp_path: Path) -> None:
    repo = _rust_python_repo(tmp_path / "repo")
    report = "# VULN-0002: RUSTSEC-2099-0001 in itoa 1.0.11\n\n**Severity:** HIGH\n**Target:** itoa 1.0.11\n"
    assert not unverified_dependency_finding(report, repo)
    (repo / "package-lock.json").write_text('{"packages": {"node_modules/lodash": {"version": "4.17.20"}}}')
    assert not unverified_dependency_finding(LODASH_REPORT, repo)


def test_findings_without_a_package_name_are_never_dropped(tmp_path: Path) -> None:
    repo = _rust_python_repo(tmp_path / "repo")
    report = "# VULN-0003: SQL injection\n\n**Severity:** HIGH\n**Endpoint:** /api/login\n"
    assert not unverified_dependency_finding(report, repo)


def test_requirements_files_are_dependency_manifests(tmp_path: Path) -> None:
    repo = _rust_python_repo(tmp_path / "repo")
    (repo / "requirements-production.in").write_text("orjson==3.10.15\n")
    report = "**Target:** orjson 3.10.15\n"

    assert not unverified_dependency_finding(report, repo)


def test_dependency_names_outside_regular_manifests_are_ignored(tmp_path: Path) -> None:
    repo = _rust_python_repo(tmp_path / "repo")
    (repo / "README.md").write_text("lodash\n")
    git_dir = repo / ".git"
    git_dir.mkdir()
    (git_dir / "Cargo.lock").write_text('[[package]]\nname = "lodash"\n')
    source = repo / "symlink-source.txt"
    source.write_text("lodash\n")
    (repo / "requirements-symlink.txt").symlink_to(source)
    oversized = repo / "requirements-oversized.txt"
    oversized.write_text("lodash\n")
    with oversized.open("ab") as handle:
        handle.truncate(9 * 1024 * 1024)

    assert unverified_dependency_finding(LODASH_REPORT, repo)


def test_main_returns_usage_error_without_both_paths(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([str(HELPER)]) == 2
    assert "Usage: strix_unverified_dependency.py REPORT REPO_ROOT" in capsys.readouterr().err


def test_main_classifies_report_and_emits_warning(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = _rust_python_repo(tmp_path / "repo")
    report = tmp_path / "vuln-0001.md"
    report.write_text(LODASH_REPORT)

    assert main([str(HELPER), str(report), str(repo)]) == 0
    assert "lodash" in capsys.readouterr().err
    (repo / "yarn.lock").write_text('lodash@^4.17.20:\n  version "4.17.20"\n')
    assert main([str(HELPER), str(report), str(repo)]) == 1


def test_script_entrypoint_exits_with_main_status(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", [str(HELPER)])

    with pytest.raises(SystemExit, match="2"):
        runpy.run_path(str(HELPER), run_name="__main__")


def test_cli_exit_status_and_message(tmp_path: Path) -> None:
    repo = _rust_python_repo(tmp_path / "repo")
    report = tmp_path / "vuln-0001.md"
    report.write_text(LODASH_REPORT)
    result = subprocess.run([sys.executable, str(HELPER), str(report), str(repo)], capture_output=True, text=True, check=False)
    assert result.returncode == 0
    assert "lodash" in result.stderr and "unverified" in result.stderr
    (repo / "yarn.lock").write_text('lodash@^4.17.20:\n  version "4.17.20"\n')
    assert subprocess.run([sys.executable, str(HELPER), str(report), str(repo)], check=False).returncode == 1
