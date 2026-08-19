"""Regression tests for Strix report blocking-signal classification."""

from __future__ import annotations

import contextlib
import importlib.util
import io
from pathlib import Path
import runpy
import sys
import tempfile
import unittest


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "ci" / "strix_report_signal.py"


def load_module():
    """Load the production helper directly from its repository path."""
    spec = importlib.util.spec_from_file_location("strix_report_signal", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load strix_report_signal")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class StrixReportSignalTests(unittest.TestCase):
    """Classify actual scanner failures without rejecting benign library warnings."""

    def setUp(self) -> None:
        self.module = load_module()

    def test_benign_hugging_face_warning_is_not_blocking(self) -> None:
        text = (
            "Warning: You are sending unauthenticated requests to the HF Hub. "
            "Please set a token to increase rate limits.\n"
            "Vulnerabilities 0\n"
        )
        self.assertFalse(self.module.contains_blocking_signal(text))

    def test_fatal_denied_and_timeout_words_are_blocking(self) -> None:
        for text in (
            "Fatal: scanner state is corrupt",
            "request Denied by policy",
            "provider Timeout while collecting evidence",
        ):
            with self.subTest(text=text):
                self.assertTrue(self.module.contains_blocking_signal(text))

    def test_structured_strix_warning_is_blocking_only_with_failure_semantics(self) -> None:
        self.assertTrue(
            self.module.contains_blocking_signal(
                "2026-08-19 10:00:00 WARNING worker - "
                "strix.core.execution: scan incomplete because provider unavailable"
            )
        )
        self.assertFalse(
            self.module.contains_blocking_signal(
                "2026-08-19 10:00:00 WARNING worker - "
                "strix.core.execution: optional cache disabled"
            )
        )

    def test_scan_ignores_non_logs_binary_files_and_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root, tempfile.TemporaryDirectory() as raw_external:
            root = Path(raw_root)
            (root / "clean.log").write_text("Warning: benign dependency warning\n", encoding="utf-8")
            (root / "not-a-log.txt").write_text("Fatal", encoding="utf-8")
            (root / "binary.log").write_bytes(b"\xff\xfe\x00Fatal")
            target = Path(raw_external) / "target.log"
            target.write_text("Fatal", encoding="utf-8")
            symlink = root / "linked.log"
            try:
                symlink.symlink_to(target)
            except OSError:
                pass
            self.assertFalse(self.module.scan_report_roots([root]))

    def test_scan_finds_blocking_signal_in_nested_regular_log(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            nested = root / "nested"
            nested.mkdir()
            (nested / "scan.log").write_text("Timeout during report generation\n", encoding="utf-8")
            self.assertTrue(self.module.scan_report_roots([root]))

    def test_module_entrypoint_uses_cli_contract(self) -> None:
        original_argv = sys.argv
        stderr = io.StringIO()
        try:
            sys.argv = [str(MODULE_PATH)]
            with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit) as raised:
                runpy.run_path(str(MODULE_PATH), run_name="__main__")
        finally:
            sys.argv = original_argv
        self.assertEqual(raised.exception.code, 2)
        self.assertIn("at least one report root", stderr.getvalue())

    def test_cli_exit_codes_match_shell_contract(self) -> None:
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            self.assertEqual(self.module.main([]), 2)
        self.assertIn("at least one report root", stderr.getvalue())

        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            (root / "clean.log").write_text("Warning: harmless\n", encoding="utf-8")
            self.assertEqual(self.module.main([str(root)]), 1)
            (root / "bad.log").write_text("Denied\n", encoding="utf-8")
            self.assertEqual(self.module.main([str(root)]), 0)
            self.assertEqual(self.module.main([str(root / "missing")]), 1)


if __name__ == "__main__":
    unittest.main()
