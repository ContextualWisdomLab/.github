"""Regression tests for the production Strix changed-path normalizer."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
GATE_SCRIPT = REPOSITORY_ROOT / "scripts" / "ci" / "strix_quick_gate.sh"
QUALITY_WORKFLOW = (
    REPOSITORY_ROOT / ".github" / "workflows" / "strix-changed-path-quality-ci.yml"
)
START_MARKER = 'python3 - "$REPO_ROOT" "$changed_file" <<\'PY\'\n'
END_MARKER = "\nPY\n}\n\nnormalize_changed_files_cache()"
LEGAL_PACKRAT_PATH = (
    "packrat/lib/x86_64-pc-linux-gnu/3.4.1/packrat/tests/testthat/"
    "Ugly, but legal, path for a project (long)/bread/DESCRIPTION"
)


def _normalizer_source() -> str:
    """Return the exact embedded Python program used in production."""

    gate_source = GATE_SCRIPT.read_text(encoding="utf-8")
    prefix, separator, remainder = gate_source.partition(START_MARKER)
    if not separator or not prefix:
        raise AssertionError("Strix changed-path normalizer start marker is missing")
    source, separator, _suffix = remainder.partition(END_MARKER)
    if not separator:
        raise AssertionError("Strix changed-path normalizer end marker is missing")
    return source


def _normalize(candidate: str) -> subprocess.CompletedProcess[str]:
    """Execute the production normalizer with an isolated repository root."""

    with tempfile.TemporaryDirectory() as temporary_directory:
        return subprocess.run(
            [sys.executable, "-c", _normalizer_source(), temporary_directory, candidate],
            check=False,
            capture_output=True,
            text=True,
        )


class StrixChangedPathPolicyTests(unittest.TestCase):
    """Verify legal Git paths and fail-closed path boundaries."""

    def test_accepts_historical_packrat_fixture_path(self) -> None:
        """A tracked Packrat fixture with commas and parentheses is valid input."""

        result = _normalize(LEGAL_PACKRAT_PATH)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), LEGAL_PACKRAT_PATH)

    def test_preserves_existing_supported_punctuation(self) -> None:
        """Existing bracket, at-sign, plus-sign, space, and hyphen support remains."""

        candidate = "ui/[slug]/128x128@2x +page-safe/file-name.ts"
        result = _normalize(candidate)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), candidate)

    def test_rejects_traversal_absolute_controls_and_shell_punctuation(self) -> None:
        """The repair does not admit traversal, controls, or shell syntax."""

        rejected = (
            "",
            ".",
            "..",
            "../secret.txt",
            "safe/../target.txt",
            "/tmp/secret.txt",
            "safe\\escape.txt",
            "safe\nname.txt",
            "safe\rname.txt",
            " leading.txt",
            "trailing.txt ",
            "safe;command.txt",
            "safe$(command).txt",
            "safe`command`.txt",
            "safe|command.txt",
            "safe&command.txt",
        )
        for candidate in rejected:
            with self.subTest(candidate=repr(candidate)):
                result = _normalize(candidate)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "")


class MergeSchedulerQualityTriggerTests(unittest.TestCase):
    """Keep scheduler control-plane changes inside an exact-head full-suite gate."""

    def test_scheduler_source_workflow_and_tests_trigger_quality_ci(self) -> None:
        """Every central merge-scheduler surface must trigger the permanent gate."""

        workflow = QUALITY_WORKFLOW.read_text(encoding="utf-8")
        for path in (
            ".github/workflows/pr-review-merge-scheduler.yml",
            "scripts/ci/pr_review_merge_scheduler.py",
            "tests/test_pr_review_merge_scheduler.py",
            "tests/test_strix_changed_path_policy.py",
        ):
            self.assertEqual(workflow.count(f'      - "{path}"'), 1)

        self.assertIn(
            "ref: ${{ github.event.pull_request.head.sha || github.sha }}",
            workflow,
        )
        self.assertIn("python -m coverage run -m pytest tests -q", workflow)
        self.assertIn("git diff --exit-code", workflow)


if __name__ == "__main__":
    unittest.main()
