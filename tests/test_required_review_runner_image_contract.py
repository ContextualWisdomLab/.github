"""Contract tests for central required review workflow runner images."""

from __future__ import annotations

from pathlib import Path
import re
import unittest


STRIX = Path(".github/workflows/strix.yml")
OPENCODE_REVIEW = Path(".github/workflows/opencode-review.yml")
NOEMA_REVIEW = Path(".github/workflows/noema-review.yml")
OPENCODE_REVIEW_DISPATCH = Path(".github/workflows/opencode-review-dispatch.yml")


class RequiredReviewRunnerImageContract(unittest.TestCase):
    """Keep required review jobs off the observed starved floating image."""

    def assert_explicit_supported_image(self, path: Path) -> None:
        """Require every ordinary job to use isolated self-hosted Linux runners."""
        workflow = path.read_text(encoding="utf-8")
        self.assertIn("group: CWL CI isolated", workflow)
        self.assertIn("labels: [self-hosted, linux, x64, cwlab-ci-isolated]", workflow)

    def test_strix_uses_explicit_supported_image(self) -> None:
        """Route trusted metadata to control while preserving the scan image."""
        workflow = STRIX.read_text(encoding="utf-8")
        for name in ("changed-scope", "admit-current-head", "cancel-superseded-pr-runs", "publish-manual-pr-evidence-status"):
            block = re.split(r"\n  [a-z][a-z-]*:\n", workflow.split(f"\n  {name}:\n", 1)[1], maxsplit=1)[0]
            self.assertIn('"group":"CWL central control"', block)
            self.assertIn('"labels":["self-hosted","linux","x64","cwlab-control"]', block)
            self.assertIn("github.workflow_ref == 'ContextualWisdomLab/.github/.github/workflows/strix.yml@refs/heads/main'", block)
            self.assertIn("github.repository == 'ContextualWisdomLab/.github'", block)
            self.assertIn("github.repository == 'ContextualWisdomLab/fast-mlsirm'", block)
            self.assertIn('fromJSON(\'{"group":"CWL CI isolated","labels":["self-hosted","linux","x64","cwlab-ci-isolated"]}\')', block)
            self.assertNotIn("actions/checkout", block)
        scan = workflow.split("\n  strix:\n", 1)[1].split("\n  publish-manual-pr-evidence-status:\n", 1)[0]
        self.assertIn("group: CWL CI isolated", scan)
        self.assertIn("labels: [self-hosted, linux, x64, cwlab-ci-isolated]", scan)
        self.assertNotIn("cwlab-control", scan)

    def test_opencode_review_uses_explicit_supported_image(self) -> None:
        """Keep metadata-only OpenCode admission on the trusted control pool."""
        workflow = "\n".join(line for line in OPENCODE_REVIEW.read_text(encoding="utf-8").splitlines() if not line.strip().startswith("labels:"))
        self.assertEqual(workflow.count('"group":"CWL central control"'), 6)
        self.assertEqual(workflow.count('"labels":["self-hosted","linux","x64"]'), 6)
        self.assertNotIn("runs-on: ubuntu-24.04", workflow)
        self.assertNotIn("actions/checkout", workflow)
        self.assertEqual(workflow.count("github.workflow_ref == 'ContextualWisdomLab/.github/.github/workflows/opencode-review.yml@refs/heads/main'"), 6)
        self.assertEqual(workflow.count('fromJSON(\'{"group":"CWL CI isolated","labels":["self-hosted","linux","x64","cwlab-ci-isolated"]}\')'), 6)

    def test_noema_review_uses_explicit_supported_image(self) -> None:
        """Keep trusted metadata jobs separate from the model review pool."""
        workflow = "\n".join(line for line in NOEMA_REVIEW.read_text(encoding="utf-8").splitlines() if not line.strip().startswith("labels:"))
        self.assertEqual(workflow.count("github.workflow_ref == 'ContextualWisdomLab/.github/.github/workflows/noema-review.yml@refs/heads/main'"), 5)
        self.assertNotIn("endsWith(github.workflow_ref", workflow)
        self.assertEqual(workflow.count('"group":"CWL MCP remediation"'), 1)
        self.assertEqual(workflow.count('"labels":["self-hosted","linux","x64"]'), 1)
        for repository in ("cwl-telemetry", "naruon", "fast-mlsirm", "late-life-anxiety-reanalysis"):
            self.assertEqual(workflow.count(f"github.repository == 'ContextualWisdomLab/{repository}'"), 5)
        self.assertEqual(workflow.count("github.repository == 'ContextualWisdomLab/contextual-orchestrator'"), 5)
        self.assertEqual(workflow.count('fromJSON(\'{"group":"CWL CI isolated","labels":["self-hosted","linux","x64","cwlab-ci-isolated"]}\')'), 5)
        self.assertNotIn("runs-on: ubuntu-24.04", workflow)
        self.assertEqual(workflow.count('"cwlab-control"'), 4)
        for name in ("admit-current-head", "changed-scope", "cancel-closed-pr-runs", "continue-noema-transport"):
            block = re.split(r"\n  [a-z][a-z-]*:\n", workflow.split(f"\n  {name}:\n", 1)[1], maxsplit=1)[0]
            self.assertIn('"group":"CWL central control"', block)
            self.assertNotIn("CWL MCP remediation", block)
            self.assertNotIn("actions/checkout", block)
        review = workflow.split("\n  noema-review:\n", 1)[1].split("\n  continue-noema-transport:\n", 1)[0]
        self.assertNotIn("cwlab-control", review)

    def test_opencode_review_dispatch_uses_explicit_supported_image(self) -> None:
        """Require OpenCode dispatch jobs to use the compatible dedicated group.

        This is the workflow the required `opencode-review` check's
        `repository_dispatch` actually lands on to run the OpenCode CLI and
        post the exact-head verdict; a starved floating image here queues
        the real review work for hours just as surely as on the required
        check itself (see docs/product-technical-gap-baseline.md's
        2026-09-01 entry, whose own "Residual" note flagged this exact
        follow-up sweep as still open).
        """
        workflow = OPENCODE_REVIEW_DISPATCH.read_text(encoding="utf-8")
        self.assertEqual(workflow.count("group: CWL central OpenCode"), 3)
        self.assertEqual(workflow.count("labels: [self-hosted, linux, x64]"), 3)
        self.assertNotIn("runs-on: ubuntu-latest", workflow)
        self.assertNotIn("runs-on: ubuntu-24.04", workflow)


if __name__ == "__main__":
    unittest.main()


def test_codeql_pr_routes_trusted_main_to_control_and_pr_revisions_to_hosted() -> None:
    """Separate short metadata work from model work without granting PR runner access."""
    workflow = "\n".join(line for line in Path(".github/workflows/codeql-pr.yml").read_text().splitlines() if not line.strip().startswith("labels:"))
    assert workflow.count('"group":"CWL central control"') == 3
    assert workflow.count("github.workflow_ref == 'ContextualWisdomLab/.github/.github/workflows/codeql-pr.yml@refs/heads/main'") == 3
    assert workflow.count("|| '{\"group\":\"CWL CI isolated\",\"labels\":[\"self-hosted\",\"linux\",\"x64\",\"cwlab-ci-isolated\"]}'") == 3
    assert '"group":"CWL MCP remediation"' not in workflow
