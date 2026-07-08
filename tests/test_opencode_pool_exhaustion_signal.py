"""Contract tests for the OpenCode model-pool exhaustion retry signal."""

import shutil
import subprocess
import sys
from pathlib import Path

from tests.test_opencode_workflow_shell_syntax import _extract_run_block

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_model_pool_runner_reports_exhaustion_distinctly():
    """The pool runner must mark quota exhaustion as a retryable, distinct status."""
    runner = (REPO_ROOT / "scripts/ci/run_opencode_review_model_pool.sh").read_text(encoding="utf-8")
    # Distinct exhaustion status, never conflated with a genuine failure or success.
    assert 'record_review_status "exhausted"' in runner
    assert "record_review_exhausted" in runner
    # Bounded cycle cap so exhaustion is reportable without relying on job timeout.
    assert "OPENCODE_POOL_MAX_CYCLES" in runner
    # The success path stays a distinct verdict.
    assert 'record_review_status "success"' in runner


def test_workflow_signals_exhaustion_as_retryable_without_approving():
    """The workflow marks exhaustion retryable via a COMMENT review, never an approval."""
    workflow = (REPO_ROOT / ".github/workflows/opencode-review.yml").read_text(encoding="utf-8")
    assert "Signal OpenCode review model-pool exhaustion" in workflow
    assert "steps.opencode_review_model_pool.outputs.review_status == 'exhausted'" in workflow
    assert "<!-- opencode-review-exhausted -->" in workflow
    # COMMENT event only: exhaustion must not approve or request changes.
    assert '"event=COMMENT"' in workflow
    marker_run = _extract_run_block(workflow, "Signal OpenCode review model-pool exhaustion")
    assert "event=APPROVE" not in marker_run
    assert "REQUEST_CHANGES" not in marker_run


def test_workflow_exhaustion_run_block_is_valid_bash():
    """The exhaustion marker run block must be valid bash so the step never crashes."""
    if sys.platform == "win32":
        return
    bash = shutil.which("bash")
    if bash is None:  # pragma: no cover - CI always provides bash
        return
    workflow = (REPO_ROOT / ".github/workflows/opencode-review.yml").read_text(encoding="utf-8")
    marker_run = _extract_run_block(workflow, "Signal OpenCode review model-pool exhaustion")
    result = subprocess.run(
        [bash, "-n"], input=marker_run, text=True, capture_output=True, check=False
    )
    assert result.returncode == 0, result.stderr
