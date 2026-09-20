"""Executable shell-boundary contract for the reusable Pages deployment workflow."""

from __future__ import annotations

import os
import re
import subprocess
import textwrap
import unittest
from pathlib import Path


WORKFLOW_PATH = Path(__file__).parents[1] / ".github" / "workflows" / "deploy-pages.yml"
ACCEPTANCE_WORKFLOW_PATH = (
    Path(__file__).parents[1]
    / ".github"
    / "workflows"
    / "deploy-pages-input-security-ci.yml"
)
CALLER_INPUT_EXPRESSIONS = {
    "PROJECT_NAME": "${{ inputs.project_name }}",
    "BUILD_DIR": "${{ inputs.build_dir }}",
    "CUSTOM_DOMAIN": "${{ inputs.custom_domain }}",
}


def _indented_blocks(text: str, key: str) -> tuple[str, ...]:
    """Return literal/folded YAML blocks for ``key`` without requiring a YAML parser."""

    lines = text.splitlines()
    blocks: list[str] = []
    start_re = re.compile(rf"^(?P<indent>\s*){re.escape(key)}:\s*[|>][-+]?\s*$")
    index = 0
    while index < len(lines):
        match = start_re.match(lines[index])
        if match is None:
            index += 1
            continue
        base_indent = len(match.group("indent"))
        index += 1
        body: list[str] = []
        while index < len(lines):
            line = lines[index]
            if line.strip() and len(line) - len(line.lstrip()) <= base_indent:
                break
            body.append(line)
            index += 1
        blocks.append("\n".join(body))
    return tuple(blocks)


def _named_step(text: str, name: str) -> str:
    """Return one workflow step block identified by its exact ``name`` field."""

    lines = text.splitlines()
    marker = f"- name: {name}"
    for index, line in enumerate(lines):
        if line.strip() != marker:
            continue
        step_indent = len(line) - len(line.lstrip())
        block = [line]
        for next_line in lines[index + 1 :]:
            if (
                next_line.strip().startswith("- name:")
                and len(next_line) - len(next_line.lstrip()) == step_indent
            ):
                break
            block.append(next_line)
        return "\n".join(block)
    raise AssertionError(f"workflow step not found: {name}")


class DeployPagesInputShellBoundaryTests(unittest.TestCase):
    """Pin caller-controlled reusable-workflow inputs outside shell source text."""

    @classmethod
    def setUpClass(cls) -> None:
        """Read the workflow once from the exact checked-out source tree."""

        cls.workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        cls.acceptance_workflow = ACCEPTANCE_WORKFLOW_PATH.read_text(encoding="utf-8")

    def test_acceptance_workflow_admits_stacked_pull_request_bases(self) -> None:
        """Pages acceptance must not exclude feature-branch PR bases."""

        lines = self.acceptance_workflow.splitlines()
        pull_request_index = lines.index("  pull_request:")
        pull_request_block: list[str] = []
        for line in lines[pull_request_index + 1 :]:
            if line and not line.startswith(" "):
                break
            if line.startswith("  ") and not line.startswith("    ") and line.strip():
                break
            pull_request_block.append(line)

        self.assertFalse(
            any(line.strip().startswith("branches:") for line in pull_request_block)
        )

    def test_caller_inputs_never_interpolate_directly_into_run_scripts(self) -> None:
        """Caller-controlled values must cross into shell scripts only through env."""

        run_blocks = _indented_blocks(self.workflow, "run")
        self.assertTrue(run_blocks, "deploy-pages.yml must contain executable run blocks")
        for run_script in run_blocks:
            for expression in CALLER_INPUT_EXPRESSIONS.values():
                self.assertNotIn(expression, run_script)

    def test_action_command_inputs_are_validated_before_wrangler(self) -> None:
        """The string-valued Wrangler command must receive only shell-safe values."""

        validation_step = _named_step(self.workflow, "Validate deployment inputs")
        validation_scripts = _indented_blocks(validation_step, "run")
        self.assertEqual(len(validation_scripts), 1)
        validation_script = textwrap.dedent(validation_scripts[0])

        valid_environment = {
            **os.environ,
            "PROJECT_NAME": "keyverse-marketing",
            "BUILD_DIR": "./public/assets_v2",
            "CUSTOM_DOMAIN": "pages.example.com",
        }
        valid_result = subprocess.run(
            ["bash", "--noprofile", "--norc", "-o", "pipefail", "-c", validation_script],
            check=False,
            capture_output=True,
            env=valid_environment,
            text=True,
        )
        self.assertEqual(valid_result.returncode, 0, valid_result.stderr)

        rejected_inputs = (
            ("PROJECT_NAME", "safe; touch /tmp/pages-command-injection"),
            ("PROJECT_NAME", "--config=attacker.toml"),
            ("BUILD_DIR", "./public && printf injected"),
            ("BUILD_DIR", "../private"),
            ("BUILD_DIR", "/tmp/public"),
            ("CUSTOM_DOMAIN", "safe.example; printf injected"),
            ("CUSTOM_DOMAIN", "line-one\nline-two.example"),
        )
        for environment_name, hostile_value in rejected_inputs:
            hostile_environment = {**valid_environment, environment_name: hostile_value}
            hostile_result = subprocess.run(
                [
                    "bash",
                    "--noprofile",
                    "--norc",
                    "-o",
                    "pipefail",
                    "-c",
                    validation_script,
                ],
                check=False,
                capture_output=True,
                env=hostile_environment,
                text=True,
            )
            self.assertNotEqual(
                hostile_result.returncode,
                0,
                f"accepted hostile {environment_name}={hostile_value!r}",
            )

        self.assertLess(
            self.workflow.index("- name: Validate deployment inputs"),
            self.workflow.index("- name: Deploy to Cloudflare Pages (wrangler)"),
        )

    def test_summary_binds_caller_inputs_through_environment(self) -> None:
        """The summary step consumes caller values from named environment variables."""

        summary = _named_step(self.workflow, "Summary")
        for variable, expression in CALLER_INPUT_EXPRESSIONS.items():
            self.assertRegex(
                summary,
                rf"(?m)^\s+{re.escape(variable)}:\s+{re.escape(expression)}\s*$",
            )
        self.assertIn("${PROJECT_NAME}", summary)
        self.assertIn("${BUILD_DIR}", summary)
        self.assertIn("${CUSTOM_DOMAIN:-(none)}", summary)


if __name__ == "__main__":  # pragma: no cover - CI uses unittest discovery directly.
    unittest.main()
