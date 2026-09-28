"""Run both native metadata guards without network or real credentials."""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.test_required_workflow_queue_contract import workflow_step, workflow_text
from tests.test_strix_repository_visibility_contract import _extract_run_block


@pytest.mark.parametrize("name", [
    "Admit only the exact live Noema head",
    "Reject a stale trigger before credential or model setup",
])
@pytest.mark.parametrize("source", ["app", "oidc", "pat", "merge", "approve"])
@pytest.mark.parametrize("current", [True, False])
def test_native_metadata_token_reaches_both_head_reads(tmp_path: Path, name: str, source: str, current: bool):
    workflow = workflow_text("noema-review.yml")
    step = workflow_step(workflow, name)
    # Admission originally inherited its legacy selector from the job.
    expression = re.search(r"GH_TOKEN: \$\{\{ (.*?) \}\}", step)
    if expression is None:
        expression = re.search(r"GH_TOKEN: \$\{\{ (.*?) \}\}", workflow)
    credentials = {
        "steps.noema_metadata_app_token.outputs.token": "synthetic-app" if source != "oidc" else "",
        "steps.noema_metadata_oidc_token.outputs.token": "synthetic-oidc" if source == "oidc" else "",
        "secrets.NOEMA_REVIEW_TOKEN": "synthetic-pat" if source == "pat" else "",
        "secrets.PR_REVIEW_MERGE_TOKEN": "synthetic-merge" if source == "merge" else "",
        "secrets.OPENCODE_APPROVE_TOKEN": "synthetic-approve" if source == "approve" else "",
        "github.token": "workflow-only",
    }
    token = next(credentials.get(term.strip()) for term in expression.group(1).split("||") if credentials.get(term.strip()))
    gh = tmp_path / "gh"
    live_head = ("a" if current else "c") * 40
    payload = json.dumps({"state": "open", "head": {"sha": live_head}, "base": {"sha": "b" * 40}})
    gh.write_text('#!/usr/bin/env bash\n'
                  '[[ "$GH_TOKEN" == "$ACCEPTED_TOKEN" ]] || exit 1\n'
                  f'if [[ "$*" == *"--jq"* ]]; then printf "%s" "{live_head}"; '
                  f"else printf '%s' '{payload}'; fi\n")
    gh.chmod(0o755)
    result = subprocess.run([shutil.which("bash") or "/bin/bash"],
        input=_extract_run_block(workflow, name), text=True, capture_output=True,
        env={**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}", "GH_TOKEN": token,
             "ACCEPTED_TOKEN": f"synthetic-{source}", "TARGET_REPOSITORY": "ContextualWisdomLab/private-example",
             "PR_NUMBER": "269", "EXPECTED_HEAD_SHA": "a" * 40, "GITHUB_OUTPUT": str(tmp_path / "output")})
    admission = name == "Admit only the exact live Noema head"
    assert (result.returncode == 0) == (source != "oidc" and (current or admission)), result.stderr
    if admission and source != "oidc":
        assert ("admitted=true" in (tmp_path / "output").read_text()) == current


@pytest.mark.parametrize("job", ["admit-current-head", "noema-review"])
@pytest.mark.parametrize("source", ["app", "oidc", "pat", "workflow", "foreign", "malformed"])
def test_native_metadata_selection_precedes_reads_and_preserves_pat_priority(tmp_path, job, source):
    workflow = workflow_text("noema-review.yml")
    body = re.split(r"\n {2}(?=\S)", workflow.split(f"\n  {job}:\n", 1)[1], maxsplit=1)[0]
    name = "Select native Noema credential for metadata reads"
    assert body.index(name) < body.index("Mint read-only native Noema GitHub App token")
    guard = "Admit only the exact live Noema head" if job == "admit-current-head" else "Reject a stale trigger before credential or model setup"
    assert body.index("Mint read-only native Noema GitHub App token") < body.index(guard)
    mint = workflow_step(body, "Mint read-only native Noema GitHub App token")
    assert "permission-pull-requests: read" in mint
    assert ": write" not in mint
    assert "bcd2ba49218906704ab6c1aa796996da409d3eb1" in mint
    assert "outputs.token" not in body.split("    steps:\n", 1)[0]
    output = tmp_path / "output"
    result = subprocess.run([shutil.which("bash") or "/bin/bash"],
        input=_extract_run_block(body, name), text=True, capture_output=True,
        env={**os.environ, "GITHUB_OUTPUT": str(output),
             "TARGET_REPOSITORY": "OtherOwner/example" if source == "foreign" else "ContextualWisdomLab/example",
             "PR_NUMBER": "269", "EXPECTED_HEAD_SHA": "bad" if source == "malformed" else "a" * 40,
             "METADATA_TOKEN": "synthetic-pat" if source == "pat" else "",
             "NOEMA_GITHUB_APP_CLIENT_ID": "synthetic-client" if source in {"app", "pat"} else "",
             "NOEMA_GITHUB_APP_PRIVATE_KEY": "synthetic-key" if source in {"app", "pat"} else "",
             "TOKEN_EXCHANGE_URL": "https://fixture.invalid/exchange" if source != "workflow" else ""})
    if source in {"foreign", "malformed"}:
        assert result.returncode != 0
        assert not output.exists()
    else:
        assert result.returncode == 0, result.stderr
        assert f"source={'github-app' if source == 'app' else 'workflow' if source == 'oidc' else source}" in output.read_text()
