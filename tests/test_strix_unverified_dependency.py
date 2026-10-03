"""Strix findings naming a package the repository does not depend on are unverified.

fast-mlsirm#2246 (run 36580588738) failed its required Strix gate on
"VULN-0001: CVE-2024-1234 in lodash 4.17.20" from the free fallback model. The
repository is Rust and Python with no JavaScript lockfile, and CVE-2024-1234 is
unrelated to lodash. With no file location the gate failed closed as unmapped.
"""

from __future__ import annotations

<<<<<<< HEAD
=======
import runpy
>>>>>>> 38a1692b (merge: integrate latest review authority into CodeQL owner)
import subprocess
import sys
from pathlib import Path

<<<<<<< HEAD
=======
import pytest

import scripts.ci.strix_unverified_dependency as unverified_dependency

>>>>>>> 38a1692b (merge: integrate latest review authority into CodeQL owner)
from scripts.ci.strix_unverified_dependency import (
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


def test_cli_exit_status_and_message(tmp_path: Path) -> None:
    repo = _rust_python_repo(tmp_path / "repo")
    report = tmp_path / "vuln-0001.md"
    report.write_text(LODASH_REPORT)
    result = subprocess.run([sys.executable, str(HELPER), str(report), str(repo)], capture_output=True, text=True, check=False)
    assert result.returncode == 0
    assert "lodash" in result.stderr and "unverified" in result.stderr
    (repo / "yarn.lock").write_text('lodash@^4.17.20:\n  version "4.17.20"\n')
    assert subprocess.run([sys.executable, str(HELPER), str(report), str(repo)], check=False).returncode == 1
<<<<<<< HEAD
=======

def test_manifest_scan_ignores_nonfiles_links_vendor_and_oversized_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only bounded regular dependency manifests influence the verdict."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "requirements-extra.in").write_text("present-package==1\n")
    (repo / "notes.txt").write_text("ignored-package==1\n")
    (repo / "requirements-big.txt").write_text("oversized-package==1\n")
    (repo / "linked.txt").symlink_to(repo / "requirements-extra.in")
    vendor = repo / "vendor"
    vendor.mkdir()
    (vendor / "package.json").write_text('{"dependencies":{"vendored-package":"1"}}')
    monkeypatch.setattr(unverified_dependency, "MAX_MANIFEST_BYTES", 20)

    manifest_text = unverified_dependency._manifest_text(repo)

    assert "present-package" in manifest_text
    assert "ignored-package" not in manifest_text
    assert "oversized-package" not in manifest_text
    assert "vendored-package" not in manifest_text


def test_main_contract_covers_usage_unverified_and_present_dependency(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    """The direct CLI contract returns 2/0/1 for usage/unverified/present."""
    assert unverified_dependency.main(["helper"]) == 2
    assert "Usage:" in capsys.readouterr().err

    repo = _rust_python_repo(tmp_path / "repo")
    report = tmp_path / "report.md"
    report.write_text(LODASH_REPORT)
    assert unverified_dependency.main(["helper", str(report), str(repo)]) == 0
    assert "express, lodash" in capsys.readouterr().err

    (repo / "package.json").write_text('{"dependencies":{"lodash":"4.17.20"}}')
    assert unverified_dependency.main(["helper", str(report), str(repo)]) == 1


def test_script_entrypoint_propagates_the_classification_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Executing the helper as a script publishes its classification as exit status."""
    repo = _rust_python_repo(tmp_path / "repo")
    report = tmp_path / "report.md"
    report.write_text(LODASH_REPORT)
    monkeypatch.setattr(sys, "argv", [str(HELPER), str(report), str(repo)])
    with pytest.raises(SystemExit, match="0"):
        runpy.run_path(str(HELPER), run_name="__main__")
>>>>>>> 38a1692b (merge: integrate latest review authority into CodeQL owner)
