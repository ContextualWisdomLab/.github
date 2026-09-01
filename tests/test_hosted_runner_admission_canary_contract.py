"""Contract tests for the bounded GitHub-hosted runner admission canary."""

from __future__ import annotations

from pathlib import Path
import unittest


CANARY = Path(".github/workflows/hosted-runner-admission-canary.yml")


class HostedRunnerAdmissionCanaryContract(unittest.TestCase):
    """Keep the canary minimal so queue evidence isolates runner admission."""

    def setUp(self) -> None:
        """Load the workflow whose shape is the diagnostic contract."""
        self.workflow = CANARY.read_text(encoding="utf-8")

    def test_trigger_is_bounded_to_canary_changes(self) -> None:
        """Run only when this temporary diagnostic or its contract changes."""
        self.assertIn("pull_request:", self.workflow)
        self.assertIn(".github/workflows/hosted-runner-admission-canary.yml", self.workflow)
        self.assertIn("tests/test_hosted_runner_admission_canary_contract.py", self.workflow)
        self.assertNotIn("schedule:", self.workflow)
        self.assertNotIn("workflow_dispatch:", self.workflow)

    def test_job_requests_only_the_floating_hosted_image(self) -> None:
        """Exclude checkout, dependencies, environments, matrices, and credentials."""
        self.assertEqual(self.workflow.count("runs-on: ubuntu-latest"), 1)
        self.assertIn("permissions: {}", self.workflow)
        for forbidden in ("uses:", "needs:", "environment:", "matrix:", "env:"):
            self.assertNotIn(forbidden, self.workflow)
        self.assertEqual(self.workflow.count("\n      - name:"), 1)
        self.assertIn('run: "true"', self.workflow)

    def test_concurrency_identity_is_unique_per_run(self) -> None:
        """Prevent the canary from cancelling or serializing another canary."""
        self.assertIn(
            "group: hosted-runner-admission-canary-${{ github.run_id }}",
            self.workflow,
        )
        self.assertIn("cancel-in-progress: false", self.workflow)


if __name__ == "__main__":
    unittest.main()
