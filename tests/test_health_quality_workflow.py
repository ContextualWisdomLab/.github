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
                    self.assertEqual(
                        step["with"]["ref"],
                        "${{ steps.admission.outputs.expected_sha }}",
                    )

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
                    "CALLER_PR_STATE": "open",
                    "CALLER_PR_HEAD_SHA": "a" * 40,
                    "CALLER_SHA": "b" * 40,
                    "CALLER_REF": "refs/pull/8/merge"
                    if event == "pull_request"
                    else "refs/heads/main",
                    "GITHUB_OUTPUT": os.devnull,
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

    def test_pr_metadata_cannot_admit_or_emit_sha_when_incomplete(self):
        """Execute the original admission shell against broken PR metadata."""
        shell = workflow()["jobs"]["quality"]["steps"][0]["run"]
        base = {
            "CALLER_REPOSITORY": "ContextualWisdomLab/health-evidence",
            "CALLER_PRIVATE": "true",
            "CALLER_EVENT": "pull_request",
            "CALLER_HEAD_REPOSITORY": "ContextualWisdomLab/health-evidence",
            "CALLER_PR_STATE": "open",
            "CALLER_PR_HEAD_SHA": "a" * 40,
            "CALLER_SHA": "b" * 40,
            "CALLER_REF": "refs/pull/8/merge",
            "HEALTH_GATE": "rust",
        }
        for override in [
            {"CALLER_PR_HEAD_SHA": ""},
            {"CALLER_PR_STATE": "closed"},
            {"CALLER_REF": "refs/pull/0/merge"},
        ]:
            with (
                self.subTest(override=override),
                tempfile.TemporaryDirectory() as directory,
            ):
                output = Path(directory) / "outputs"
                output.touch()
                result = subprocess.run(
                    ["bash", "-c", shell],
                    env={
                        **os.environ,
                        **base,
                        **override,
                        "GITHUB_OUTPUT": str(output),
                    },
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertEqual(output.read_text(), "")

    def test_admission_outputs_bind_merge_candidate_and_reject_controls(self):
        """Only full admission emits the event SHA, never a PR head fallback."""
        step = workflow()["jobs"]["quality"]["steps"][0]
        for key, expression in {
            "CALLER_PR_STATE": "${{ github.event.pull_request.state }}",
            "CALLER_PR_HEAD_SHA": "${{ github.event.pull_request.head.sha }}",
            "CALLER_SHA": "${{ github.sha }}",
            "CALLER_REF": "${{ github.ref }}",
        }.items():
            self.assertEqual(step["env"][key], expression)
        base = {
            "CALLER_REPOSITORY": "ContextualWisdomLab/health-evidence",
            "CALLER_PRIVATE": "true",
            "CALLER_EVENT": "pull_request",
            "CALLER_HEAD_REPOSITORY": "ContextualWisdomLab/health-evidence",
            "CALLER_PR_STATE": "open",
            "CALLER_PR_HEAD_SHA": "a" * 40,
            "CALLER_SHA": "b" * 40,
            "CALLER_REF": "refs/pull/8/merge",
            "HEALTH_GATE": "rust",
        }
        cases = [({}, True)]
        for key, values in {
            "CALLER_REPOSITORY": ["", "outsider/repository"],
            "CALLER_PRIVATE": ["", "false"],
            "CALLER_EVENT": ["", "pull_request_target", "schedule"],
            "CALLER_HEAD_REPOSITORY": ["", "outsider/fork"],
            "CALLER_PR_STATE": ["", "closed", "OPEN"],
            "CALLER_PR_HEAD_SHA": ["", "A" * 40, "a" * 39, "g" * 40, "a" * 41],
            "CALLER_SHA": ["", "B" * 40, "b" * 39, "g" * 40, "b" * 41],
            "CALLER_REF": [
                "",
                "refs/pull/0/merge",
                "refs/pull/-1/merge",
                "refs/pull/08/merge",
                "refs/pull/8/head",
                "refs/heads/main",
            ],
            "HEALTH_GATE": ["", "unrecognized"],
        }.items():
            cases.extend(({key: value}, False) for value in values)
        for event in ["push", "workflow_dispatch"]:
            cases.append(
                (
                    {
                        "CALLER_EVENT": event,
                        "CALLER_REF": "refs/heads/feature/valid",
                        "CALLER_PR_STATE": "",
                        "CALLER_PR_HEAD_SHA": "",
                        "CALLER_HEAD_REPOSITORY": "",
                    },
                    True,
                )
            )
            for ref in [
                "",
                "refs/heads/",
                "refs/tags/v1",
                "refs/pull/8/merge",
                "refs/heads/bad..ref",
                "refs/heads/bad ref",
                "refs/heads/.hidden",
            ]:
                cases.append(({"CALLER_EVENT": event, "CALLER_REF": ref}, False))
        for override, admitted in cases:
            with (
                self.subTest(override=override),
                tempfile.TemporaryDirectory() as directory,
            ):
                output = Path(directory) / "outputs"
                output.touch()
                result = subprocess.run(
                    ["bash", "-c", step["run"]],
                    env={
                        **os.environ,
                        **base,
                        **override,
                        "GITHUB_OUTPUT": str(output),
                    },
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                self.assertEqual(result.returncode == 0, admitted, result.stderr)
                self.assertEqual(
                    output.read_text(),
                    "expected_sha=" + base["CALLER_SHA"] + "\nadmitted=true\n"
                    if admitted
                    else "",
                )

    def test_job_guard_precedes_runner_and_requires_metadata(self):
        """Scheduling rejection is defense in depth, not passing evidence."""
        job = workflow()["jobs"]["quality"]
        guard = job["if"]
        for requirement in [
            "github.repository == 'ContextualWisdomLab/health-evidence'",
            "github.event.repository.private == true",
            'contains(fromJSON(\'["documentation","rust","pwa"]\'), inputs.gate)',
            "github.sha != ''",
            "github.event.pull_request.state == 'open'",
            "github.event.pull_request.head.repo.full_name == github.repository",
            "github.event.pull_request.head.sha != ''",
            "github.event_name == 'pull_request'",
            "github.event_name == 'push'",
            "github.event_name == 'workflow_dispatch'",
            "github.event.pull_request.number > 0",
            "github.ref == format('refs/pull/{0}/merge', github.event.pull_request.number)",
            "startsWith(github.ref, 'refs/heads/')",
        ]:
            self.assertIn(requirement, guard)
        self.assertIn("NOT executed quality evidence", WORKFLOW.read_text())

    def test_checkout_head_assertion_executes_before_product_gates(self):
        """Execute the actual HEAD guard with matching and mismatching identities."""
        steps = workflow()["jobs"]["quality"]["steps"]
        step = steps[2]
        self.assertEqual(step["name"], "Assert admitted checkout identity")
        head = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip()
        for sha, admitted, success in [
            (head, "true", True),
            ("0" * 40, "true", False),
            ("", "true", False),
            (head, "", False),
        ]:
            with self.subTest(sha=sha, admitted=admitted):
                result = subprocess.run(
                    ["bash", "-c", step["run"]],
                    cwd=ROOT,
                    env={**os.environ, "EXPECTED_SHA": sha, "ADMITTED": admitted},
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                self.assertEqual(result.returncode == 0, success, result.stderr)

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
        for step in steps[3:]:
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
