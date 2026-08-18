"""Regression contracts for issue 952's trusted Strix runtime boundary."""

from __future__ import annotations

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "strix.yml"
GATE = ROOT / "scripts" / "ci" / "strix_quick_gate.sh"
SEMANTICS = ROOT / "scripts" / "ci" / "strix_report_semantics.py"
VALIDATOR = ROOT / "scripts" / "ci" / "validate_strix_runtime_compatibility.py"


def load_module(path: Path, name: str):
    """Load a repository script as a module without changing sys.path."""
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"could not load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class WorkflowContractTests(unittest.TestCase):
    """Protect the base-executed pull_request_target installation path."""

    def test_complete_hashed_lock_is_installed_without_reresolution(self) -> None:
        """The base workflow must consume the closed lock without pip resolution."""
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn(
            "--require-hashes --no-deps -r requirements-strix-ci-hashes.txt",
            workflow,
        )
        self.assertIn("validate_strix_runtime_compatibility.py", workflow)

    def test_incomplete_backend_scan_cannot_become_success(self) -> None:
        """No provider outage may turn an incomplete required scan into success."""
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertNotIn("Treating as a neutral skip", workflow)
        self.assertNotIn("backend_unavailable_signal=", workflow)
        self.assertIn('exit "$strix_rc"', workflow)

    def test_gate_imports_authoritative_target_reports_before_judgment(self) -> None:
        """The gate must evaluate reports written under the exact scan target."""
        gate = GATE.read_text(encoding="utf-8")
        self.assertIn("import-current-attempt", gate)
        self.assertIn('"${resolved_target_path%/}/strix_runs"', gate)
        self.assertIn("vulnerability_file_is_self_negating_no_finding", gate)


class ReportSemanticsTests(unittest.TestCase):
    """Verify narrow contradictory no-finding classification and safe import."""

    def setUp(self) -> None:
        """Load the standalone semantics module for each isolated test."""
        self.module = load_module(SEMANTICS, "strix_report_semantics")

    def test_scopeweave_self_negating_high_record_is_not_a_finding(self) -> None:
        """HIGH metadata cannot override multiple explicit no-finding claims."""
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "finding.md"
            report.write_text(
                "# No JWT Authentication Vulnerabilities Found\n\n"
                "Severity: HIGH\nCVSS: 7.3\n\n"
                "N/A - No vulnerabilities discovered.\n"
                "No immediate remediation is required.\n",
                encoding="utf-8",
            )
            self.assertTrue(self.module.is_self_negating_report(report))

    def test_real_finding_with_negative_control_language_is_preserved(self) -> None:
        """Positive exploit and source evidence defeat no-finding classification."""
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "finding.md"
            report.write_text(
                "# JWT Authentication Bypass\n\nSeverity: HIGH\n"
                "The negative control found no issue, but the affected endpoint "
                "accepts an unsigned token.\nTarget: backend/auth.py:42\n"
                "Proof of concept: send alg=none.\n",
                encoding="utf-8",
            )
            self.assertFalse(self.module.is_self_negating_report(report))

    def test_single_no_remediation_phrase_is_not_enough(self) -> None:
        """A real informational finding cannot be suppressed by one mild phrase."""
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "finding.md"
            report.write_text(
                "# Weak hardening recommendation\nSeverity: LOW\n"
                "No immediate remediation is required, but the affected component "
                "should be hardened.\nLocation: backend/config.py:10\n",
                encoding="utf-8",
            )
            self.assertFalse(self.module.is_self_negating_report(report))

    def test_current_attempt_import_rejects_symlinked_output(self) -> None:
        """Untrusted report trees cannot escape through a symlink."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            destination = root / "destination"
            outside = root / "outside.md"
            source.mkdir()
            destination.mkdir()
            outside.write_text("Severity: HIGH", encoding="utf-8")
            vulnerabilities = source / "run" / "vulnerabilities"
            vulnerabilities.mkdir(parents=True)
            (vulnerabilities / "escape.md").symlink_to(outside)
            with self.assertRaises(ValueError):
                self.module.import_current_attempt_reports(source, destination, 0)

    def test_current_attempt_import_ignores_stale_files(self) -> None:
        """Only files created or changed during this attempt enter evaluation."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            destination = root / "destination"
            vulnerabilities = source / "run" / "vulnerabilities"
            vulnerabilities.mkdir(parents=True)
            report = vulnerabilities / "stale.md"
            report.write_text("Severity: HIGH", encoding="utf-8")
            os.utime(report, (1, 1))
            copied = self.module.import_current_attempt_reports(
                source, destination, started_at_epoch=10
            )
            self.assertEqual(copied, 0)
            self.assertFalse((destination / "run" / "vulnerabilities" / "stale.md").exists())


class RuntimeCompatibilityTests(unittest.TestCase):
    """Verify exact-pin parsing independently of installed third-party modules."""

    def test_lock_parser_reads_exact_strix_and_cryptography_pins(self) -> None:
        """The runtime smoke must attest the versions present in the hash lock."""
        module = load_module(VALIDATOR, "validate_strix_runtime_compatibility")
        with tempfile.TemporaryDirectory() as directory:
            lock = Path(directory) / "requirements.txt"
            lock.write_text(
                "strix-agent==1.5.3 --hash=sha256:abc\n"
                "cryptography==50.0.0 --hash=sha256:def\n",
                encoding="utf-8",
            )
            self.assertEqual(
                module.required_runtime_pins(lock),
                {"strix-agent": "1.5.3", "cryptography": "50.0.0"},
            )


if __name__ == "__main__":
    unittest.main()
