"""Execute canonical intake guards for the two exact MLLO owners."""

import os
from pathlib import Path
import re
import subprocess
import textwrap

import pytest


@pytest.mark.parametrize("suffix", ["", "-design"])
def test_hyosung_intake_preserves_dispatch_authority(suffix):
    """Exact scope cannot replace matching dispatcher identity and live metadata."""
    target = "HYOSUNG-ITX-AI-Business-Department/llm-gateway-console" + suffix
    workflow = Path(".github/workflows/opencode-review-dispatch.yml").read_text()
    section = workflow.split("      - name: Bind workflow inputs to live organization pull request metadata\n", 1)[1]
    program = textwrap.dedent(section.split("        run: |\n", 1)[1].split("          pull_request_json=", 1)[0])
    env = dict(os.environ, EVENT_NAME="repository_dispatch", DISPATCH_ACTOR="opencode-agent[bot]", DISPATCH_SENDER="opencode-agent[bot]", ALLOWED_DISPATCH_ACTOR="opencode-agent[bot]", ALLOWED_DISPATCH_TARGETS=target, TARGET_REPOSITORY=target, PR_NUMBER="1")
    for overrides, expected in (({}, 0), ({"DISPATCH_SENDER": "forged"}, 1), ({"ALLOWED_DISPATCH_TARGETS": ""}, 1), ({"PR_NUMBER": "0"}, 1)):
        result = subprocess.run(["bash", "-c", program], env={**env, **overrides}, capture_output=True, text=True)
        assert result.returncode == expected, result.stdout


@pytest.mark.parametrize("filename", ["opencode-review.yml", "opencode-review-dispatch.yml"])
def test_only_exact_hyosung_names_pass(filename):
    """Both guards reject near names even if the external allowlist lists them."""
    source = Path(".github/workflows", filename).read_text()
    pattern, = re.findall(r'"\$TARGET_REPOSITORY" =~ (\^[^ ]+)', source)
    owner = "HYOSUNG-ITX-AI-Business-Department/llm-gateway-console"
    for target, accepted in ((owner, True), (owner + "-design", True), (owner + "-extra", False), (owner + "-design-extra", False), (owner + "/extra", False), (owner + "\n", False), ("other/llm-gateway-console", False)):
        result = subprocess.run(["bash", "-c", '[[ "$TARGET_REPOSITORY" =~ ' + pattern + ' ]]'], env=dict(os.environ, TARGET_REPOSITORY=target), capture_output=True)
        assert (result.returncode == 0) == accepted
