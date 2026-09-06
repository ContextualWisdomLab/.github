"""Regression for CodeQL reruns whose earlier attempts never reached dispatch."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from tests.test_opencode_workflow_shell_syntax import _extract_run_block


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPO_ROOT / ".github/workflows/codeql-pr.yml"
DISPATCH_STEP_NAME = "Request current-head CodeQL scan dispatch"


def test_rerun_without_authenticated_verdict_can_redispatch(tmp_path: Path) -> None:
    """A later attempt may dispatch when earlier attempts never produced a verdict."""
    bash = shutil.which("bash")
    jq = shutil.which("jq")
    assert bash is not None and jq is not None

    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    script = _extract_run_block(workflow, DISPATCH_STEP_NAME)
    head_sha = "b" * 40
    base_sha = "a" * 40

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    dispatch_body = tmp_path / "dispatch.json"

    fake_gh = fake_bin / "gh"
    fake_gh.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'test "$1" = api\n'
        "shift\n"
        'if [ "${1:-}" = "-X" ]; then\n'
        '  test "$2" = POST\n'
        '  test "$3" = "repos/ContextualWisdomLab/.github/dispatches"\n'
        '  cat >"$FAKE_DISPATCH_BODY"\n'
        "  exit 0\n"
        "fi\n"
        'if [ "${1:-}" = "--paginate" ]; then\n'
        '  test "${2:-}" = "--slurp"\n'
        '  case "${3:-}" in\n'
        "    */statuses?per_page=100) printf '%s\\n' '[[]]' ;;\n"
        "    *) exit 1 ;;\n"
        "  esac\n"
        "  exit 0\n"
        "fi\n"
        'case "$1" in\n'
        "  */pulls/*) printf '%s\\n' \"$FAKE_PULL_JSON\" ;;\n"
        "  *) exit 1 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    fake_gh.chmod(0o755)

    fake_curl = fake_bin / "curl"
    fake_curl.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'last="${@: -1}"\n'
        'case "$last" in\n'
        "  *audience=opencode-github-action) printf '%s\\n' '{\"value\":\"oidc-token\"}' ;;\n"
        "  */exchange_github_app_token) printf '%s\\n' '{\"token\":\"app-token\"}' ;;\n"
        "  *) exit 1 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    fake_curl.chmod(0o755)

    output = tmp_path / "github-output"
    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "FAKE_PULL_JSON": json.dumps({"head": {"sha": head_sha}, "state": "open"}),
        "FAKE_DISPATCH_BODY": str(dispatch_body),
        "GH_TOKEN": "leaf-token",
        "OIDC_AUDIENCE": "opencode-github-action",
        "OPENCODE_API_BASE_URL": "https://api.opencode.ai",
        "TARGET_REPOSITORY": "ContextualWisdomLab/accounting-information-platform",
        "PR_NUMBER": "49",
        "PR_BASE_REF": "develop",
        "PR_BASE_SHA": base_sha,
        "PR_HEAD_REF": "fix/restore-accounting-doc-ci-evidence",
        "PR_HEAD_SHA": head_sha,
        "LANGUAGE": "python",
        "BUILD_MODE": "none",
        "RUN_ATTEMPT": "3",
        "REQUIRED_RUN_ID": "33890965185",
        "REQUIRED_JOB_ID": "101220582747",
        "ACTIONS_ID_TOKEN_REQUEST_TOKEN": "request-token",
        "ACTIONS_ID_TOKEN_REQUEST_URL": "https://oidc.example/token",
        "GITHUB_OUTPUT": str(output),
    }

    result = subprocess.run(
        [bash],
        input=script,
        text=True,
        capture_output=True,
        check=False,
        env=env,
        timeout=60,
    )

    assert result.returncode == 0, result.stderr
    assert "verdict=pending" in output.read_text(encoding="utf-8")
    payload = json.loads(dispatch_body.read_text(encoding="utf-8"))
    assert payload["event_type"] == "codeql-scan"
    client_payload = payload["client_payload"]
    assert client_payload["target_repository"] == "ContextualWisdomLab/accounting-information-platform"
    assert client_payload["pr_head_sha"] == head_sha
    assert client_payload["required_run_id"] == "33890965185"
    assert client_payload["required_job_id"] == "101220582747"
    assert client_payload["required_language"] == "python"


def test_status_lookup_paginates_complete_history_before_redispatch() -> None:
    """Recovery must inspect every commit-status page before treating verdict as absent."""
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    script = _extract_run_block(workflow, DISPATCH_STEP_NAME)

    assert (
        'gh api --paginate --slurp '
        '"repos/${TARGET_REPOSITORY}/commits/${PR_HEAD_SHA}/statuses?per_page=100"'
        in script
    )
    assert ".[][]" in script
