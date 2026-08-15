"""Regression tests for trusted base Python lock preflight classification."""

from __future__ import annotations

import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_NAME = "_install_base_python_locks_under_test"
MODULE_PATH = Path("scripts/ci/install_base_python_locks.py")
SPEC = importlib.util.spec_from_file_location(MODULE_NAME, MODULE_PATH)
if SPEC is None or SPEC.loader is None:  # pragma: no cover - import guard
    raise RuntimeError(f"Could not load {MODULE_PATH}")
LOCKS = importlib.util.module_from_spec(SPEC)
sys.modules[MODULE_NAME] = LOCKS
SPEC.loader.exec_module(LOCKS)

ATHERIS_DISTRIBUTION_GAP = """\
ERROR: Could not find a version that satisfies the requirement atheris==3.0.0 (from versions: 3.1.0)
ERROR: No matching distribution found for atheris==3.0.0
"""


class DistributionGapClassificationTests(unittest.TestCase):
    """Cover pip diagnostics that distinguish safe deferral from outages."""

    def test_index_resolved_distribution_gap_is_deferable(self) -> None:
        """A pinned package with visible alternative versions may be skipped."""
        self.assertTrue(
            LOCKS._is_deferable_preflight_failure(ATHERIS_DISTRIBUTION_GAP)
        )

    def test_network_failure_remains_fatal(self) -> None:
        """A registry outage must not masquerade as interpreter incompatibility."""
        output = (
            "WARNING: Retrying after connection broken by "
            "'Temporary failure in name resolution'.\n"
            + ATHERIS_DISTRIBUTION_GAP
        )
        self.assertFalse(LOCKS._is_deferable_preflight_failure(output))

    def test_empty_available_version_set_remains_fatal(self) -> None:
        """An index response without alternatives is not compatibility evidence."""
        output = """\
        ERROR: Could not find a version that satisfies the requirement missing==9.9.9 (from versions: none)
        ERROR: No matching distribution found for missing==9.9.9
        """
        self.assertFalse(LOCKS._is_deferable_preflight_failure(output))

    def test_mismatched_requirements_remain_fatal(self) -> None:
        """The two pip diagnostics must describe the same exact requirement."""
        output = """\
        ERROR: Could not find a version that satisfies the requirement first==1.0 (from versions: 2.0)
        ERROR: No matching distribution found for second==1.0
        """
        self.assertFalse(LOCKS._is_deferable_preflight_failure(output))

    def test_unexplained_no_matching_distribution_remains_fatal(self) -> None:
        """A lone resolver failure cannot be silently skipped."""
        self.assertFalse(
            LOCKS._is_deferable_preflight_failure(
                "ERROR: No matching distribution found for unknown==1.0"
            )
        )

    def test_install_skips_index_resolved_distribution_gap(self) -> None:
        """Coverage image construction continues past an optional foreign wheel."""
        with tempfile.TemporaryDirectory() as temp_directory:
            root = Path(temp_directory)
            (root / "manifest.json").write_text(
                json.dumps(
                    [
                        {
                            "file": "requirements-000.txt",
                            "source": "fuzz/requirements-atheris.txt",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            (root / "requirements-000.txt").write_text(
                "atheris==3.0.0 --hash=sha256:" + "0" * 64 + "\n",
                encoding="utf-8",
            )
            calls: list[list[str]] = []

            def runner(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
                calls.append(command)
                if "--dry-run" not in command:
                    raise AssertionError("a deferred candidate must not be installed")
                return subprocess.CompletedProcess(
                    command,
                    1,
                    stdout=ATHERIS_DISTRIBUTION_GAP,
                )

            stdout = io.StringIO()
            stderr = io.StringIO()
            result = LOCKS.install_materialized_locks(
                root,
                runner=runner,
                stdout=stdout,
                stderr=stderr,
            )

        self.assertEqual(result, 0)
        self.assertEqual(len(calls), 1)
        self.assertIn("installed=0 skipped=1", stdout.getvalue())
        self.assertIn("Skipping trusted base Python requirement candidate", stderr.getvalue())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
