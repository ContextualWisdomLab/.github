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


def _workflow() -> dict[str, object]:
    """Load the reviewed Noema workflow from the current repository tree."""
    return yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))


def _steps() -> list[dict[str, object]]:
    """Return the ordered Noema review step list for sequencing assertions."""
    return _workflow()["jobs"]["noema-review"]["steps"]


def _step(name: str) -> dict[str, object]:
    """Return one named Noema review step from the production workflow."""
    return next(step for step in _steps() if step.get("name") == name)


def _step_index(name: str) -> int:
    """Return a named production step's position in the Noema review job."""
    return next(index for index, step in enumerate(_steps()) if step.get("name") == name)


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


def test_publication_revalidation_uses_fresh_repository_scoped_authority() -> None:
    """Private sibling publication refreshes expiring authorities before its live check."""
    app_refresh_name = "Refresh repository-scoped Noema GitHub App token for publication"
    oidc_refresh_name = "Refresh repository-scoped Noema OIDC app token for publication"
    publish_check_name = "Revalidate live Noema target before publication"
    publish_name = "Publish prepared Noema verdict on the exact live head"

    assert _step_index(app_refresh_name) < _step_index(publish_check_name)
    assert _step_index(oidc_refresh_name) < _step_index(publish_check_name)

    app_refresh = _step(app_refresh_name)
    oidc_refresh = _step(oidc_refresh_name)
    live_publish = _step(publish_check_name)
    publish = _step(publish_name)

    assert "steps.noema_prepare.outputs.prepared == 'true'" in str(app_refresh.get("if", ""))
    assert "steps.noema_credential.outputs.source == 'github-app'" in str(app_refresh.get("if", ""))
    assert "steps.noema_prepare.outputs.prepared == 'true'" in str(oidc_refresh.get("if", ""))
    assert "steps.noema_credential.outputs.source == 'oidc'" in str(oidc_refresh.get("if", ""))

    live_token_expression = str(live_publish.get("env", {}).get("GH_TOKEN", ""))
    assert "NOEMA_REVIEW_TOKEN" in live_token_expression
    assert "noema_github_app_publication_token.outputs.token" in live_token_expression
    assert "noema_oidc_publication_token.outputs.token" in live_token_expression
    assert "github.token" not in live_token_expression
    assert "noema_github_app_token.outputs.token" not in live_token_expression
    assert "noema_oidc_token.outputs.token" not in live_token_expression

    publish_token_expression = str(publish.get("env", {}).get("GH_TOKEN", ""))
    assert "noema_github_app_publication_token.outputs.token" in publish_token_expression
    assert "noema_oidc_publication_token.outputs.token" in publish_token_expression
    assert "steps.noema_oidc_token.outputs.token" not in publish_token_expression
    assert "github.token" not in publish_token_expression
