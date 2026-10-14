"""Source-only regression for the central security bundle reusable entrypoint.

Scanner execution, runner admission and exact consumer context publication are
separate acceptance gates. This test does not manufacture any runtime result.
"""

from pathlib import Path
import json
import os
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/security-scan.yml"
BASE = "acb8b34f9e7b8649fa1478139fa21c2217bdfbc7"


def test_reusable_entrypoint_preserves_entire_security_bundle() -> None:
    """Expose the existing bundle without changing a scanner or its permissions."""
    original = subprocess.check_output(
        ["git", "show", f"{BASE}:.github/workflows/security-scan.yml"],
        cwd=ROOT,
    )
    current = WORKFLOW.read_bytes()
    addition = b"  workflow_call: {}\n"
    assert current.count(addition) == 1, "missing explicit reusable security ingress"
    admission_start = current.index(b"  admit-security-pr:\n", current.index(b"jobs:\n"))
    admission_end = current.index(b"  changed-scope:\n", admission_start)
    admission = current[admission_start:admission_end]
    assert b"    permissions: {}\n" in admission
    assert b"uses:" not in admission and b"checkout" not in admission.split(b"run: |", 1)[0]
    assert current.count(b"    needs: admit-security-pr\n") == 2
    assert b"  changed-scope:\n    needs: admit-security-pr\n" in current
    assert b"  gitleaks:\n    needs: admit-security-pr\n" in current
    restored = current[:admission_start] + current[admission_end:]
    restored = restored.replace(addition, b"", 1).replace(b"    needs: admit-security-pr\n", b"")
    assert restored == original, "scanner bodies, scope and permissions changed"


@pytest.mark.parametrize(
    "paths,expected_count,expected",
    [
        ("README.md\n", "1", {"code": "false", "deps": "false"}),
        ("python/example.py\n", "1", {"code": "true", "deps": "false"}),
        ("Cargo.lock\n", "1", {"code": "true", "deps": "true"}),
        ("README.md\n", "2", {"code": "true", "deps": "true"}),
    ],
)
def test_actual_scope_shell_preserves_scanner_applicability(
    tmp_path: Path, paths: str, expected_count: str, expected: dict[str, str]
) -> None:
    """Characterize actual scope code with synthetic file-list transport only."""
    text = WORKFLOW.read_text(encoding="utf-8")
    start = text.index("        run: |\n", text.index("- name: Classify changed paths"))
    lines = text[start:].splitlines()[1:]
    body = []
    for line in lines:
        if line.strip() and not line.startswith("          "):
            break
        body.append(line[10:])
    assert body and body[0] == "set -uo pipefail"
    tools = tmp_path / "bin"
    tools.mkdir()
    gh = tools / "gh"
    gh.write_text('#!/bin/sh\nprintf "%s" "$FIXTURE_PATHS"\n', encoding="utf-8")
    gh.chmod(0o700)
    output = tmp_path / "outputs"
    bash = shutil.which("bash")
    assert bash, "Bash is required; do not skip source-shell contracts"
    result = subprocess.run(
        [bash, "-c", "\n".join(body)],
        cwd=tmp_path,
        env={
            "PATH": str(tools) + os.pathsep + "/usr/bin:/bin",
            "FIXTURE_PATHS": paths,
            "REPO": "ContextualWisdomLab/fast-mlsirm",
            "PR": "2302",
            "EXPECTED_FILES": expected_count,
            "GITHUB_OUTPUT": str(output),
        },
        text=True,
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    actual = dict(line.split("=", 1) for line in output.read_text().splitlines())
    assert actual == expected


def step_body(text: str, name: str) -> str:
    """Extract the complete literal run body of a named native workflow step."""
    start = text.index("        run: |\n", text.index(f"- name: {name}"))
    body = []
    for line in text[start:].splitlines()[1:]:
        if line.strip() and not line.startswith("          "):
            break
        body.append(line[10:])
    return "\n".join(body)


@pytest.mark.parametrize("event_name,action,mutation,allowed", [
    ("issues", "closed", "", False),
    ("push", "", "missing_pr", False),
    ("workflow_dispatch", "", "missing_pr", False),
    ("pull_request", "opened", "missing_pr", False),
    ("pull_request", "opened", "sha", False),
    ("pull_request", "opened", "repository", False),
    ("pull_request", "opened", "number", False),
    ("pull_request", "opened", "", True),
    ("pull_request_target", "synchronize", "fork", True),
    ("pull_request", "closed", "", True),
    ("pull_request", "edited", "", True),
    ("pull_request", "converted_to_draft", "", True),
    ("pull_request", "", "", False),
])
def test_actual_admission_rejects_unsupported_event_before_scanners(
    tmp_path: Path, event_name: str, action: str, mutation: str, allowed: bool
) -> None:
    """Execute native admission, or predecessor scope for causal rejection RED."""
    import sys

    repository = "ContextualWisdomLab/fast-mlsirm"
    pr = {"number": 2302,
          "base": {"repo": {"full_name": repository}, "sha": "a" * 40, "ref": "main"},
          "head": {"repo": {"full_name": repository}, "sha": "b" * 40, "ref": "feature"}}
    event = {"number": 2302, "action": action, "pull_request": pr}
    if mutation == "missing_pr":
        del event["pull_request"]
    elif mutation == "sha":
        pr["head"]["sha"] = "main"
    elif mutation == "repository":
        pr["base"]["repo"]["full_name"] = "other/repository"
    elif mutation == "number":
        event["number"] = 42
    elif mutation == "fork":
        pr["head"]["repo"]["full_name"] = "fork-owner/fast-mlsirm"
    event_path = tmp_path / "event.json"
    event_path.write_text(json.dumps(event), encoding="utf-8")
    text = WORKFLOW.read_text(encoding="utf-8")
    name = "Validate security PR admission"
    if f"- name: {name}" in text:
        argv = [sys.executable, "-c", step_body(text, name)]
    else:
        # Original real scope code with no PR context returns0: not a mock guard.
        argv = [shutil.which("bash"), "-c", step_body(text, "Classify changed paths")]
    result = subprocess.run(argv, cwd=tmp_path, capture_output=True, text=True,
        timeout=10, env={"PATH": "/usr/bin:/bin", "GITHUB_EVENT_PATH": str(event_path),
            "EVENT_NAME": event_name, "TARGET_REPOSITORY": repository,
            "PR": "", "EXPECTED_FILES": "", "GITHUB_OUTPUT": str(tmp_path / "output")})
    if allowed:
        assert result.returncode == 0, result.stderr
    else:
        assert result.returncode != 0, "unsupported security invocation was admitted"
        assert "Invalid security PR admission" in result.stderr
