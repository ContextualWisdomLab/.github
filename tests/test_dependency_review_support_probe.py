"""Behavioral regressions for the dependency-review capability probe."""

from __future__ import annotations

import os
import stat
import subprocess
import textwrap
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _support_probe_script() -> str:
    """Extract the exact shell body used by the dependency-review support step."""
    workflow = (
        REPO_ROOT / ".github" / "workflows" / "security-scan.yml"
    ).read_text(encoding="utf-8")
    step_marker = "      - name: Check dependency review support\n"
    step_start = workflow.index(step_marker)
    run_marker = "        run: |\n"
    run_start = workflow.index(run_marker, step_start) + len(run_marker)
    run_end = workflow.index("\n      - name:", run_start)
    return textwrap.dedent(workflow[run_start:run_end])


def test_dependency_review_probe_rejects_curl_failure_with_http_200(tmp_path) -> None:
    """A transport failure must fail closed even when curl printed HTTP 200."""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_curl = fake_bin / "curl"
    fake_curl.write_text("#!/bin/sh\nprintf '200'\nexit 18\n", encoding="utf-8")
    fake_curl.chmod(fake_curl.stat().st_mode | stat.S_IXUSR)
    github_output = tmp_path / "github-output.txt"
    environment = os.environ.copy()
    environment.update(
        {
            "PATH": f"{fake_bin}:{environment['PATH']}",
            "GH_TOKEN": "test-token",
            "BASE_SHA": "a" * 40,
            "HEAD_SHA": "b" * 40,
            "REPOSITORY": "ContextualWisdomLab/example",
            "GITHUB_API_URL": "https://api.github.invalid",
            "GITHUB_OUTPUT": str(github_output),
        }
    )

    completed = subprocess.run(
        ["bash", "-c", _support_probe_script()],
        cwd=REPO_ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode != 0
    assert "Failing closed" in f"{completed.stdout}\n{completed.stderr}"
    assert not github_output.exists() or "supported=true" not in github_output.read_text(
        encoding="utf-8"
    )
