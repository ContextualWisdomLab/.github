"""Regression contract for LiteLLM ModelBehaviorError as provider flake.

A Strix run that exits 1 with ModelBehaviorError and Vulnerabilities 0 is
infrastructure noise, not a security finding. Real Vulnerabilities 1-9 must
still fail closed.
"""

from __future__ import annotations

import re
import subprocess
import tempfile
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
STRIX_WORKFLOW = REPOSITORY_ROOT / ".github" / "workflows" / "strix.yml"


def _workflow_signal_pattern(workflow: str, variable_name: str) -> str:
    """Extract one single-quoted POSIX ERE assigned in the Strix workflow."""

    match = re.search(
        rf"(?m)^\s+{re.escape(variable_name)}='([^']+)'$",
        workflow,
    )
    if match is None:
        raise AssertionError(f"missing workflow signal: {variable_name}")
    return match.group(1)


def _workflow_neutralizes(log_text: str) -> bool:
    """Execute the outer workflow's backend-neutralization condition."""

    workflow = STRIX_WORKFLOW.read_text(encoding="utf-8")
    backend_pattern = _workflow_signal_pattern(
        workflow,
        "backend_unavailable_signal",
    )
    vulnerability_pattern = _workflow_signal_pattern(
        workflow,
        "reported_vulnerability_signal",
    )
    with tempfile.TemporaryDirectory(prefix="strix-modelbehavior-") as temp_dir:
        log_path = Path(temp_dir) / "strix.log"
        log_path.write_text(log_text, encoding="utf-8")
        backend = subprocess.run(
            ["grep", "-Eiq", backend_pattern, str(log_path)],
            check=False,
            capture_output=True,
            text=True,
        )
        vulnerability = subprocess.run(
            ["grep", "-Eiq", vulnerability_pattern, str(log_path)],
            check=False,
            capture_output=True,
            text=True,
        )
    if backend.returncode not in {0, 1}:
        raise AssertionError(backend.stderr)
    if vulnerability.returncode not in {0, 1}:
        raise AssertionError(vulnerability.stderr)
    return backend.returncode == 0 and vulnerability.returncode == 1


class StrixModelBehaviorErrorFallbackTests(unittest.TestCase):
    """Treat LiteLLM ModelBehaviorError as backend flake, not a finding."""

    def test_workflow_classifies_litellm_model_behavior_error(self) -> None:
        workflow = STRIX_WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("litellm(\\.exceptions)?\\.ModelBehaviorError", workflow)
        self.assertIn("Vulnerabilities[[:space:]]+[1-9]", workflow)
        self.assertIn(
            '! grep -Eiq "$reported_vulnerability_signal"',
            workflow,
        )

    def test_model_behavior_error_with_zero_findings_is_neutral(self) -> None:
        self.assertTrue(
            _workflow_neutralizes(
                "litellm.exceptions.ModelBehaviorError: Invalid tool call\n"
                "Vulnerabilities 0\n"
            )
        )

    def test_bare_model_behavior_error_without_litellm_is_not_neutral(self) -> None:
        self.assertFalse(
            _workflow_neutralizes(
                "source literal: ModelBehaviorError in application logs\n"
                "Vulnerabilities 0\n"
            )
        )

    def test_model_behavior_error_never_neutralizes_reported_vulnerabilities(self) -> None:
        self.assertFalse(
            _workflow_neutralizes(
                "litellm.exceptions.ModelBehaviorError: Invalid tool call\n"
                "Vulnerabilities 1\n"
            )
        )


if __name__ == "__main__":
    unittest.main()
