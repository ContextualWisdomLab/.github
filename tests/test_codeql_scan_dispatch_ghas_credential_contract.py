"""Credential-routing contract for cross-repository GHAS CodeQL analysis reads."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from tests.test_opencode_workflow_shell_syntax import _extract_run_block


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPO_ROOT / ".github/workflows/codeql-scan-dispatch.yml"
SELECT_STEP_NAME = "Select target CodeQL analysis-read credential"
VERIFY_STEP_NAME = "Verify GHAS base/head CodeQL configuration identity"


def _run_selector(tmp_path: Path, *, succeeding_token: str | None) -> subprocess.CompletedProcess[str]:
    """Execute the extracted selector with fixed Bash identity and a fake ``gh`` boundary."""
    assert Path("/bin/bash").is_file(), "/bin/bash is required to run this workflow-contract test"

    workflow_text = WORKFLOW_PATH.read_text(encoding="utf-8")
    script = _extract_run_block(workflow_text, SELECT_STEP_NAME)

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir(parents=True)
    call_log = tmp_path / "calls"
    fake_gh = fake_bin / "gh"
    fake_gh.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'printf \'%s\\n\' "${GH_TOKEN:-<empty>}" >>"$FAKE_CALL_LOG"\n'
        'test "$1" = api\n'
        'test "$#" -eq 6\n'
        'test "$2" = -H\n'
        'test "$3" = "Accept: application/vnd.github+json"\n'
        'test "$4" = -H\n'
        'test "$5" = "X-GitHub-Api-Version: 2022-11-28"\n'
        'test "$6" = "repos/ContextualWisdomLab/OriginWeave/code-scanning/analyses?per_page=1&tool_name=CodeQL"\n'
        'if [ -n "${SUCCEEDING_TOKEN:-}" ] && [ "${GH_TOKEN:-}" = "$SUCCEEDING_TOKEN" ]; then\n'
        "  printf '[]\\n'\n"
        "  exit 0\n"
        "fi\n"
        "exit 1\n",
        encoding="utf-8",
    )
    fake_gh.chmod(0o755)

    output = tmp_path / "github-output"
    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "GITHUB_OUTPUT": str(output),
        "FAKE_CALL_LOG": str(call_log),
        "SUCCEEDING_TOKEN": succeeding_token or "",
        "TARGET_REPOSITORY": "ContextualWisdomLab/OriginWeave",
        "TARGET_APP_TOKEN": "content-token",
        "PR_REVIEW_MERGE_TOKEN": "security-token",
        "OPENCODE_APPROVE_TOKEN": "approve-token",
        "WORKFLOW_TOKEN": "workflow-token",
    }
    result = subprocess.run(
        ["/bin/bash"],
        input=script,
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    result.output_path = output  # type: ignore[attr-defined]
    result.call_log = call_log  # type: ignore[attr-defined]
    return result


def test_ghas_analysis_read_falls_through_content_only_target_app_token(tmp_path: Path) -> None:
    """A content-capable app token must not mask a later GHAS-capable credential."""
    result = _run_selector(tmp_path, succeeding_token="security-token")

    assert result.returncode == 0, result.stdout + result.stderr
    output = result.output_path.read_text(encoding="utf-8")
    assert "token=security-token" in output
    assert "source=pr-review-merge-token" in output
    assert result.call_log.read_text(encoding="utf-8").splitlines() == [
        "content-token",
        "security-token",
    ]


def test_ghas_analysis_read_fails_closed_when_no_candidate_can_read_target(tmp_path: Path) -> None:
    """Missing target code-scanning read authority must remain a hard prerequisite failure."""
    result = _run_selector(tmp_path, succeeding_token=None)

    assert result.returncode != 0
    assert "no configured credential can read target CodeQL analyses" in result.stdout
    assert result.call_log.read_text(encoding="utf-8").splitlines() == [
        "content-token",
        "security-token",
        "approve-token",
        "workflow-token",
    ]


def test_ghas_identity_step_consumes_only_probed_analysis_read_token() -> None:
    """The identity proof must not repeat the unprobed content-token precedence chain."""
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    verify_script = _extract_run_block(workflow, VERIFY_STEP_NAME)
    verify_prefix = workflow.split(f"      - name: {VERIFY_STEP_NAME}\n", 1)[1].split("        run: |", 1)[0]

    assert "GH_TOKEN: ${{ steps.ghas_analysis_token.outputs.token }}" in verify_prefix
    assert "steps.target_app_token.outputs.token ||" not in verify_prefix
    assert "codeql_ghas_configuration_identity.py" in verify_script
