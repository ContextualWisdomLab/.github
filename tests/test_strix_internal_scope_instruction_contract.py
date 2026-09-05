"""Protect Strix's interpretation of bounded pull-request scan targets."""

from pathlib import Path
import unittest


SCRIPT_PATH = Path("scripts/ci/strix_quick_gate.sh")


class InternalScopeInstructionContractTests(unittest.TestCase):
    """Keep static sandbox guidance scoped to trusted PR materialization."""

    @classmethod
    def setUpClass(cls) -> None:
        """Load the gate implementation once for contract assertions."""
        cls.script = SCRIPT_PATH.read_text(encoding="utf-8")

    def test_guidance_explains_the_sandbox_mount_contract(self) -> None:
        """Tell Strix why the runner host path is absent without hiding code."""
        self.assertIn(
            "deliberately bounded pull-request changed-file scope",
            self.script,
        )
        self.assertIn("/workspace/<workspace_subdir>", self.script)
        self.assertIn("host path is intentionally absent", self.script)
        self.assertIn("complete authorized target", self.script)
        self.assertIn("actionable content vulnerabilities", self.script)

    def test_guidance_is_only_selected_for_internal_pr_scope(self) -> None:
        """Never relay caller-controlled instructions to the security agent."""
        expected = (
            'if [ "$TARGET_PATH_IS_INTERNAL_PR_SCOPE" -eq 1 ]; then\n'
            '\t\tchild_instruction="$INTERNAL_PR_SCOPE_INSTRUCTION"\n'
            '\tfi'
        )
        self.assertIn(expected, self.script)
        self.assertIn('local child_instruction=""', self.script)
        self.assertNotIn(
            'STRIX_CHILD_INSTRUCTION="${STRIX_INSTRUCTION',
            self.script,
        )

    def test_child_process_receives_the_static_cli_instruction(self) -> None:
        """Forward the trusted guidance through the stripped child environment."""
        self.assertIn(
            'STRIX_CHILD_INSTRUCTION="$child_instruction"',
            self.script,
        )
        self.assertIn(
            'instruction = os.environ.get("STRIX_CHILD_INSTRUCTION", "").strip()',
            self.script,
        )
        self.assertIn(
            'command.extend(["--instruction", instruction])',
            self.script,
        )


if __name__ == "__main__":
    unittest.main()
