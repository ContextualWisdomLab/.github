import re
import shutil
import subprocess
import sys
from pathlib import Path

from tests.test_opencode_workflow_shell_syntax import _extract_run_block


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPO_ROOT / ".github/workflows/codeql-pr.yml"


def test_codeql_pr_workflow_structure() -> None:
    """codeql-pr.yml stays required-workflow-safe: no codeql-action, dispatch+poll instead.

    See docs/adr/0025-codeql-required-workflow-dispatch-architecture.md.
    codeql-action/init and codeql-action/analyze are categorically disallowed
    inside a required workflow (docs/doctoring/codeql-pr-required-workflow-always-fails.md);
    this is the permanent regression guard the ADR's own follow-up asks for --
    a future edit that reintroduces either reference here would recreate the
    exact org-wide startup_failure incident that fix exists to prevent.
    """
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "name: CodeQL PR" in workflow
    assert "branches: [main, master, develop]" not in workflow
    assert "Do not restrict the base ref" in workflow
    assert "uses: github/codeql-action" not in workflow
    assert "detect-languages:" in workflow
    assert "java-kotlin" in workflow
    assert "-name '*.java'" in workflow
    assert "-name '*.kt'" in workflow
    assert "analyze-head:" in workflow
    # analyze-merge is required nowhere (PR #1766) and is dropped, not
    # migrated, per the ADR's explicit scope decision.
    assert "analyze-merge:" not in workflow
    assert "CodeQL merge preview" not in workflow
    assert "refs/pull/{0}/merge" not in workflow
    assert "event_type:\"codeql-scan\"" in workflow
    assert "repos/ContextualWisdomLab/.github/dispatches" in workflow
    # Polls for the context codeql-scan-dispatch.yml publishes; doesn't
    # publish it itself (that happens on the .github side only).
    assert '--arg ctx "codeql-dispatch/${LANGUAGE}"' in workflow
    assert "commits/${HEAD_SHA}/statuses" in workflow


def test_codeql_pr_dispatches_one_language_per_shard_not_the_full_matrix() -> None:
    """Every shard dispatches, but only its own language, not the full matrix.

    Two designs were tried and rejected before this one (see
    docs/adr/0025-codeql-required-workflow-dispatch-architecture.md history
    and .github#1778's review thread): (a) only the first shard dispatches
    with the full matrix, which leaves every OTHER shard blind to that one
    shard's dispatch failure -- each polls the full 3-hour deadline before
    self-timing-out for a scan that was never requested; (b) every shard
    dispatches the full matrix, which triggers N redundant full-matrix scans
    on the .github side. Dispatching one shard's own single language avoids
    both: N dispatches total (same real work as one N-language dispatch),
    and each shard can read its own steps.dispatch.outcome for the poll step
    below to fail closed immediately, not after 3 hours.
    """
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "id: dispatch" in workflow
    assert 'matrix:[{language:$language,"build-mode":$build_mode}]' in workflow
    assert "needs.detect-languages.outputs.matrix).include[0]" not in workflow
    assert "DISPATCH_OUTCOME: ${{ steps.dispatch.outcome }}" in workflow
    assert workflow.count("- name: Request current-head CodeQL scan dispatch") == 1
    assert workflow.count("- name: Fail closed without a current-head CodeQL dispatch verdict") == 1


RUN_BLOCK_STEP_NAMES = (
    "Request current-head CodeQL scan dispatch",
    "Fail closed without a current-head CodeQL dispatch verdict",
)


def test_codeql_pr_dispatch_and_poll_run_blocks_are_valid_bash() -> None:
    """Both run: blocks in analyze-head must be syntactically valid Bash."""
    workflow_text = WORKFLOW_PATH.read_text(encoding="utf-8")

    if sys.platform == "win32":
        return
    bash = shutil.which("bash")
    if bash is None:
        return

    for step_name in RUN_BLOCK_STEP_NAMES:
        script = _extract_run_block(workflow_text, step_name)
        result = subprocess.run(
            [bash, "-n"],
            input=script,
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, f"{step_name}: {result.stderr}"


def test_codeql_action_steps_use_one_version_per_workflow() -> None:
    """Prevent CodeQL init/analyze version splits from failing the scheduled scan."""
    workflow = (REPO_ROOT / ".github/workflows/scheduled-security-scan.yml").read_text(
        encoding="utf-8"
    )
    refs = set(
        re.findall(
            r"github/codeql-action/(?:init|analyze|upload-sarif)@([0-9a-f]{40})",
            workflow,
        )
    )

    assert len(refs) == 1, f"scheduled-security-scan.yml mixes CodeQL action refs: {sorted(refs)}"
