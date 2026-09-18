"""Executable shell-boundary contract for the reusable Pages deployment workflow."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


WORKFLOW_PATH = Path(__file__).parents[1] / ".github" / "workflows" / "deploy-pages.yml"
CALLER_INPUT_EXPRESSIONS = {
    "PROJECT_NAME": "${{ inputs.project_name }}",
    "BUILD_DIR": "${{ inputs.build_dir }}",
    "CUSTOM_DOMAIN": "${{ inputs.custom_domain }}",
}


def _deploy_steps() -> list[dict[str, Any]]:
    """Load the reusable workflow steps as executable contract data."""

    payload = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    return payload["jobs"]["deploy_pages"]["steps"]


def test_caller_inputs_never_interpolate_directly_into_run_scripts() -> None:
    """Caller-controlled values must cross into shell scripts only through env."""

    for step in _deploy_steps():
        run_script = step.get("run")
        if not isinstance(run_script, str):
            continue
        for expression in CALLER_INPUT_EXPRESSIONS.values():
            assert expression not in run_script, (
                f"{step.get('name', '<unnamed>')} interpolates {expression} directly into run:"
            )


def test_summary_binds_caller_inputs_through_environment() -> None:
    """The summary step consumes caller values from named environment variables."""

    summary = next(step for step in _deploy_steps() if step.get("name") == "Summary")
    assert summary["env"] == CALLER_INPUT_EXPRESSIONS

    run_script = summary["run"]
    assert "${PROJECT_NAME}" in run_script
    assert "${BUILD_DIR}" in run_script
    assert "${CUSTOM_DOMAIN:-(none)}" in run_script
