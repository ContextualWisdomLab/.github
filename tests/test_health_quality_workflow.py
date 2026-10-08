"""Executable admission and gate-preservation contract for Health central CI."""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/health-quality.yml"


def workflow():
    """Load the central YAML without executing candidate repository code."""
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


class HealthQualityTests(unittest.TestCase):
    """Require caller isolation, pinned actions and all existing product gates."""

    def test_reusable_only_and_self_hosted_no_secrets(self):
        """Require only reusable calls, fixed self-hosted routing and pinned actions."""
        data = workflow()
        self.assertEqual(
            data.get("on", data.get(True)),
            {
                "workflow_call": {
                    "inputs": {"gate": {"required": True, "type": "string"}}
                }
            },
        )
        self.assertEqual(data["permissions"], {"contents": "read"})
        job = data["jobs"]["quality"]
        self.assertEqual(
            job["runs-on"],
            {
                "group": "CWL health CI",
                "labels": ["self-hosted", "Linux", "X64", "cwlab"],
            },
        )
        self.assertNotIn("secrets", WORKFLOW.read_text())
        for step in job["steps"]:
            if "uses" in step:
                self.assertRegex(step["uses"], r"@[0-9a-f]{40}$")
                if step["uses"].startswith("actions/checkout@"):
                    self.assertIs(step["with"]["persist-credentials"], False)
                    self.assertEqual(step["with"]["path"], "health-source")
                    self.assertEqual(step["with"]["ref"], "${{ github.sha }}")

    def test_admission_runs_before_checkout_and_rejects_untrusted_inputs(self):
        """Execute caller admission controls before any candidate checkout."""
        steps = workflow()["jobs"]["quality"]["steps"]
        step = steps[0]
        self.assertEqual(step["name"], "Admit private Health caller")
        self.assertIn("run", step)
        cases = [
            ("ContextualWisdomLab/health-evidence", "true", "push", "", "rust", True),
            (
                "ContextualWisdomLab/health-evidence",
                "true",
                "pull_request",
                "ContextualWisdomLab/health-evidence",
                "pwa",
                True,
            ),
            (
                "ContextualWisdomLab/health-evidence",
                "true",
                "workflow_dispatch",
                "",
                "documentation",
                True,
            ),
            (
                "ContextualWisdomLab/health-evidence",
                "true",
                "pull_request",
                "outsider/fork",
                "rust",
                False,
            ),
            ("outsider/repository", "true", "push", "", "rust", False),
            ("ContextualWisdomLab/health-evidence", "false", "push", "", "rust", False),
            (
                "ContextualWisdomLab/health-evidence",
                "true",
                "pull_request_target",
                "ContextualWisdomLab/health-evidence",
                "rust",
                False,
            ),
            (
                "ContextualWisdomLab/health-evidence",
                "true",
                "push",
                "",
                "rust; touch /tmp/forbidden",
                False,
            ),
        ]
        for repo, private, event, head, gate, admitted in cases:
            with self.subTest(repo=repo, event=event, gate=gate):
                env = {
                    **os.environ,
                    "CALLER_REPOSITORY": repo,
                    "CALLER_PRIVATE": private,
                    "CALLER_EVENT": event,
                    "CALLER_HEAD_REPOSITORY": head,
                    "HEALTH_GATE": gate,
                }
                result = subprocess.run(
                    ["bash", "-c", step["run"]],
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                self.assertEqual(result.returncode == 0, admitted, result.stderr)
        self.assertTrue(steps[1]["uses"].startswith("actions/checkout@"))

    def test_policy_environment_is_reset_before_installation(self):
        """A reused runner must not execute a prior run's policy interpreter."""
        step = next(
            s
            for s in workflow()["jobs"]["quality"]["steps"]
            if s.get("name") == "Verify Actions routing policy"
        )
        self.assertLess(
            step["run"].index('rm -rf -- "$POLICY_ENV"'),
            step["run"].index('python3 -m venv "$POLICY_ENV"'),
        )
        self.assertIn("github.run_id", step["env"]["POLICY_ENV"])
        self.assertIn("github.run_attempt", step["env"]["POLICY_ENV"])

    def test_cleanup_is_authorized_and_never_uses_untrusted_gate_as_path(self):
        """Rejected inputs must not authorize deletion on a persistent runner."""
        steps = workflow()["jobs"]["quality"]["steps"]
        self.assertEqual(steps[0].get("id"), "admission")
        cleanup = next(s for s in steps if s.get("name") == "Remove policy environment")
        self.assertIn("steps.admission.outcome == 'success'", cleanup["if"])
        for step in steps:
            if "POLICY_ENV" in step.get("env", {}):
                self.assertNotIn("inputs.gate", step["env"]["POLICY_ENV"])

    def test_policy_shell_removes_stale_files_and_preserves_failure(self):
        """Run the shipped shell twice with synthetic interpreter boundaries."""
        step = next(
            s
            for s in workflow()["jobs"]["quality"]["steps"]
            if s.get("name") == "Verify Actions routing policy"
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tools = root / "tools"
            tools.mkdir()
            python = tools / "python3"
            python.write_text(
                '#!/bin/bash\nset -eu\n[[ "$1" == "-m" && "$2" == "venv" ]]\n'
                'mkdir -p "$3/bin"\n'
                'printf \'#!/bin/bash\\nif [[ "$2" == "unittest" ]]; then exit 7; fi\\nexit 0\\n\' > "$3/bin/python"\n'
                'chmod +x "$3/bin/python"\n'
            )
            python.chmod(0o700)
            policy = root / "policy"
            unrelated = root / "unrelated"
            unrelated.write_text("preserve")
            env = {
                **os.environ,
                "PATH": f"{tools}:{os.environ['PATH']}",
                "POLICY_ENV": str(policy),
            }
            for _ in range(2):
                policy.mkdir(exist_ok=True)
                stale = policy / "stale"
                stale.write_text("old")
                result = subprocess.run(
                    ["bash", "-c", step["run"]],
                    env=env,
                    cwd=root,
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                self.assertEqual(result.returncode, 7, result.stderr)
                self.assertFalse(stale.exists())
                self.assertEqual(unrelated.read_text(), "preserve")

    def test_original_commands_versions_and_failure_semantics_are_preserved(self):
        """Keep every original product gate, toolchain pin and failure policy."""
        job = workflow()["jobs"]["quality"]
        steps = job["steps"]
        commands = "\n".join(s.get("run", "") for s in steps)
        for command in [
            "python3 .github/scripts/verify-docs.py",
            "cargo fmt --all -- --check",
            "cargo test --workspace --locked",
            "cargo clippy --workspace --locked --all-targets -- -D warnings",
            "node --test apps/pwa/tests/model.test.mjs apps/pwa/tests/client.test.mjs",
        ]:
            self.assertIn(command, commands)
        self.assertIn(
            "unittest discover -s .github/tests -p 'test_actions_policy.py' -v",
            commands,
        )
        self.assertIn("--require-hashes", commands)
        self.assertIn("pyyaml==6.0.3", commands)
        self.assertIn("CARGO_BUILD_JOBS", job["env"])
        self.assertEqual(str(job["env"]["CARGO_BUILD_JOBS"]), "1")
        self.assertNotIn("continue-on-error", str(job))
        for step in steps[2:]:
            if step.get("name") != "Remove policy environment":
                self.assertIn("inputs.gate", step.get("if", ""))
        rust = next(
            s for s in steps if s.get("uses", "").startswith("dtolnay/rust-toolchain@")
        )
        node = next(
            s for s in steps if s.get("uses", "").startswith("actions/setup-node@")
        )
        self.assertEqual(rust["with"]["toolchain"], "1.98.0")
        self.assertEqual(node["with"]["node-version"], "24.21.0")


if __name__ == "__main__":
    unittest.main()
