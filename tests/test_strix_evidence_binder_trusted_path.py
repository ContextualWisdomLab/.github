"""The Strix evidence binder resolves from the trusted gate, not the scanned repo."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

GATE = Path("scripts/ci/strix_quick_gate.sh")


def _function_source(name: str) -> str:
    """Return one top-level bash function from the gate script."""
    text = GATE.read_text(encoding="utf-8")
    match = re.search(rf"(?ms)^{name}\(\) \{{\n.*?^\}}\n", text)
    assert match is not None, name
    return match.group(0)


def test_binder_runs_when_the_scanned_repository_has_no_central_scripts(tmp_path: Path) -> None:
    """A consumer repository (for example fast-mlsirm) has no scripts/ci binder.

    ``strix.yml`` runs the trusted ``.github`` gate with ``STRIX_REPO_ROOT`` set
    to the consumer's base checkout, so ``REPO_ROOT`` has no
    ``scripts/ci/strix_evidence_binding.py``. fast-mlsirm#2005/#2018 then
    exited 2 after zero vulnerabilities with "Strix evidence binder is
    missing: …/trusted-workspace/scripts/ci/strix_evidence_binding.py". The
    binder must resolve next to the gate script instead.
    """
    consumer = tmp_path / "trusted-workspace"
    consumer.mkdir()
    reports = tmp_path / "strix_runs"
    reports.mkdir()
    report = reports / "penetration_test_report.md"
    report.write_text("# Report\n\nNo vulnerabilities were identified.\n", encoding="utf-8")
    log = tmp_path / "strix.log"
    log.write_text("scan complete\n", encoding="utf-8")
    script = (
        "set -u\n"
        f'SCRIPT_DIR="{GATE.parent.resolve()}"\n'
        f'REPO_ROOT="{consumer}"\n'
        + _function_source("sanitize_remediation_evidence_claims")
        + f'sanitize_remediation_evidence_claims "{log}" "{reports}"\n'
    )
    result = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    assert "binder is missing" not in result.stderr
    assert report.read_text(encoding="utf-8").startswith("# Report")


def test_binder_still_fails_closed_when_the_trusted_copy_is_absent(tmp_path: Path) -> None:
    """Without the trusted binder the gate still refuses to continue."""
    script = (
        "set -u\n"
        f'SCRIPT_DIR="{tmp_path}"\n'
        f'REPO_ROOT="{GATE.parent.parent.resolve()}"\n'
        + _function_source("sanitize_remediation_evidence_claims")
        + 'sanitize_remediation_evidence_claims "" ""\n'
    )
    result = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=False)
    assert result.returncode == 2
    assert f"Strix evidence binder is missing: {tmp_path}/strix_evidence_binding.py" in result.stderr
