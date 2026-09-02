"""Regressions for private cross-repository Noema live-state admission."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "noema-review.yml"


def _step(name: str) -> dict[str, object]:
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    return next(step for step in workflow["jobs"]["noema-review"]["steps"] if step.get("name") == name)


def test_cross_repository_preflight_defers_private_lookup_until_scoped_credential(tmp_path: Path) -> None:
    """The central repository token must not be used to query a private sibling."""
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash is required for the workflow-shell regression")

    step = _step("Validate live Noema target before any setup")
    script = str(step["run"])
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_gh = fake_bin / "gh"
    fake_gh.write_text("#!/usr/bin/env bash\nexit 97\n", encoding="utf-8")
    fake_gh.chmod(0o755)
    output = tmp_path / "github-output"
    output.write_text("", encoding="utf-8")

    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "GITHUB_OUTPUT": str(output),
        "GITHUB_REPOSITORY": "ContextualWisdomLab/.github",
        "TARGET_REPOSITORY": "ContextualWisdomLab/private-sibling",
        "PR_NUMBER": "42",
        "EXPECTED_HEAD_SHA": "a" * 40,
    }
    result = subprocess.run([bash, "-c", script], env=env, text=True, capture_output=True, check=False)

    assert result.returncode == 0, result.stderr
    assert "proceed=true" in output.read_text(encoding="utf-8")
    assert "defer" in result.stdout.lower()


def test_post_credential_refresh_uses_selected_repository_scoped_token() -> None:
    """Authoritative cross-repository state lookup uses the minted reviewer credential."""
    step = _step("Revalidate live Noema target before model setup")
    token_expression = str(step.get("env", {}).get("GH_TOKEN", ""))
    assert "NOEMA_REVIEW_TOKEN" in token_expression
    assert "noema_github_app_token.outputs.token" in token_expression
    assert "noema_oidc_token.outputs.token" in token_expression
    assert "github.token" not in token_expression
