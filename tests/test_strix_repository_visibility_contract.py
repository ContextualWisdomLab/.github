"""Runtime contract for Strix repository visibility routing."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.test_required_workflow_queue_contract import workflow_step


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = REPO_ROOT / ".github/workflows/strix.yml"


@pytest.mark.parametrize(
    "mode,response,available",
    [
        ("valid", '{"token":"synthetic-app"}', True),
        ("missing-oidc", '{"token":"synthetic-app"}', False),
        ("curl-failure", '{"token":"synthetic-app"}', False),
        ("multiple-oidc", '{"token":"synthetic-app"}', False),
        ("valid", '{"token":"one"} {"token":"two"}', False),
        ("malformed-oidc", '{"token":"synthetic-app"}', False),
        ("nul-oidc", '{"token":"synthetic-app"}', False),
        ("soh-oidc", '{"token":"synthetic-app"}', False),
        ("valid", '{"token":[]}', False),
        ("valid", "not-json", False),
        ("valid", "{}", False),
        ("valid", '{"token":"bad\\noutput=value"}', False),
        ("valid", '{"token":"bad\\u0000token"}', False),
        ("valid", '{"token":"bad\\u0001token"}', False),
    ],
)
def test_strix_metadata_exchange_masks_only_valid_job_local_tokens(
    tmp_path: Path, mode: str, response: str, available: bool
) -> None:
    """Exercise the actual exchange shell without network or real credentials."""
    workflow = WORKFLOW.read_text()
    step_name = "Exchange OpenCode app token for Strix target repository metadata reads"
    step = workflow_step(workflow, step_name)
    assert "github.event_name == 'repository_dispatch'" in step
    assert "target_repository != github.repository" in step
    assert "github.repository_owner" in step
    fake_curl = tmp_path / "curl"
    fake_curl.write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        '[[ "$FAKE_MODE" != curl-failure ]] || exit 22\n'
        'if [[ "$FAKE_MODE" == multiple-oidc ]]; then printf \'{"value":"one"} {"value":"two"}\'; exit 0; fi\n'
        'if [[ "$FAKE_MODE" == malformed-oidc ]]; then printf \'{"value":[]}\'; exit 0; fi\n'
        'if [[ "$FAKE_MODE" == nul-oidc ]]; then printf \'{"value":"bad\\u0000token"}\'; exit 0; fi\n'
        'if [[ "$FAKE_MODE" == soh-oidc ]]; then printf \'{"value":"bad\\u0001token"}\'; exit 0; fi\n'
        'if [[ "$*" == *"-X POST"* ]]; then printf "%s" "$FAKE_RESPONSE"; '
        'else printf \'{"value":"synthetic-oidc"}\'; fi\n'
    )
    fake_curl.chmod(0o755)
    output = tmp_path / "output"
    env = {
        **os.environ,
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "GITHUB_OUTPUT": str(output),
        "FAKE_MODE": mode,
        "FAKE_RESPONSE": response,
        "OIDC_AUDIENCE": "opencode-github-action",
        "OPENCODE_API_BASE_URL": "https://fixture.invalid",
    }
    env.pop("ACTIONS_ID_TOKEN_REQUEST_TOKEN", None)
    env.pop("ACTIONS_ID_TOKEN_REQUEST_URL", None)
    if mode != "missing-oidc":
        env.update(
            ACTIONS_ID_TOKEN_REQUEST_TOKEN="synthetic-request",
            ACTIONS_ID_TOKEN_REQUEST_URL="https://fixture.invalid/oidc",
        )
    result = subprocess.run(
        [shutil.which("bash") or "/bin/bash"],
        input=_extract_run_block(workflow, step_name),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    values = dict(line.split("=", 1) for line in output.read_text().splitlines())
    assert values == (
        {"available": "true", "token": "synthetic-app"}
        if available
        else {"available": "false"}
    )
    assert ("::add-mask::synthetic-app" in result.stdout) == available
    job_outputs = workflow.split("  admit-current-head:\n", 1)[1].split(
        "    steps:\n", 1
    )[0]
    assert "outputs.token" not in job_outputs


@pytest.mark.parametrize(
    "app,fallback,current,owner_ok,success,admitted",
    [
        ("synthetic-app", "wrong-scope", True, True, True, True),
        ("", "valid-metadata", True, True, True, True),
        ("", "wrong-scope", True, True, False, False),
        ("synthetic-app", "wrong-scope", False, True, True, False),
        ("synthetic-app", "wrong-scope", True, False, False, False),
    ],
)
def test_strix_private_admission_uses_metadata_route_and_keeps_tuple_guard(
    tmp_path: Path,
    app: str,
    fallback: str,
    current: bool,
    owner_ok: bool,
    success: bool,
    admitted: bool,
) -> None:
    """Run the real admission shell across app, fallback, 404 and stale routes."""
    workflow = WORKFLOW.read_text()
    step_name = "Verify event metadata against the live pull request"
    step = workflow_step(workflow, step_name)
    expression = re.search(r"GH_TOKEN: \$\{\{ (.*?) \}\}", step).group(1)
    values = {
        "steps.metadata_read_app_token.outputs.token": app,
        "secrets.PR_REVIEW_MERGE_TOKEN": fallback,
        "github.token": "workflow-only",
    }
    token = next(
        (
            values.get(term.strip(), "")
            for term in expression.split("||")
            if values.get(term.strip(), "")
        ),
        "",
    )
    repository = (
        "ContextualWisdomLab" if owner_ok else "OtherOwner"
    ) + "/private-example"
    payload = json.dumps(
        {
            "state": "open",
            "base": {"repo": {"full_name": repository}, "ref": "main", "sha": "c" * 40},
            "head": {
                "repo": {"full_name": repository},
                "sha": ("a" if current else "b") * 40,
            },
        }
    )
    calls = tmp_path / "calls"
    gh = tmp_path / "gh"
    gh.write_text(
        '#!/usr/bin/env bash\nset -euo pipefail\nprintf "called" > "$FAKE_GH_CALLS"\n'
        'if [[ "$GH_TOKEN" != synthetic-app && "$GH_TOKEN" != valid-metadata ]]; '
        'then echo "gh: Not Found (HTTP 404)" >&2; exit 1; fi\n'
        f"printf '%s' '{payload}'\n"
    )
    gh.chmod(0o755)
    output = tmp_path / "output"
    result = subprocess.run(
        [shutil.which("bash") or "/bin/bash"],
        input=_extract_run_block(workflow, step_name),
        env={
            **os.environ,
            "PATH": f"{tmp_path}:{os.environ['PATH']}",
            "GH_TOKEN": token,
            "FAKE_GH_CALLS": str(calls),
            "GITHUB_OUTPUT": str(output),
            "EVENT_NAME": "repository_dispatch",
            "EXPECTED_REPOSITORY_OWNER": "ContextualWisdomLab",
            "TARGET_REPOSITORY": repository,
            "TARGET_PR_NUMBER": "269",
            "EXPECTED_BASE_REF": "main",
            "EXPECTED_BASE_SHA": "c" * 40,
            "EXPECTED_HEAD_REPOSITORY": repository,
            "EXPECTED_HEAD_SHA": "a" * 40,
        },
        text=True,
        capture_output=True,
        check=False,
    )
    assert (result.returncode == 0) == success, result.stderr
    assert ("admitted=true" in output.read_text()) == admitted
    assert calls.exists() == owner_ok

def _extract_run_block(workflow_text: str, step_name: str) -> str:
    lines = workflow_text.splitlines()
    step_index = next(
        index for index, line in enumerate(lines) if line.strip() == f"- name: {step_name}"
    )
    run_index = next(
        index
        for index in range(step_index + 1, len(lines))
        if lines[index].strip() == "run: |"
    )
    run_indent = len(lines[run_index]) - len(lines[run_index].lstrip())
    block_lines: list[str] = []
    for line in lines[run_index + 1 :]:
        if line.strip() and len(line) - len(line.lstrip()) <= run_indent:
            break
        block_lines.append(line[run_indent + 2 :] if len(line) >= run_indent + 2 else "")
    return "\n".join(block_lines) + "\n"


def _run_visibility_step(
    tmp_path: Path,
    event_visibility: str,
    *,
    api_visibility: str = "",
) -> subprocess.CompletedProcess[str]:
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash is required for the extracted workflow regression")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    gh_log = tmp_path / "gh-log"
    fake_gh = fake_bin / "gh"
    fake_gh.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' "$*" >> "$FAKE_GH_LOG"
test "$1" = api
case "$*" in
  *visibility*) ;;
  *) echo "visibility query required" >&2; exit 64 ;;
esac
case "$FAKE_REPOSITORY_VISIBILITY" in
  public) printf 'false\\n' ;;
  private | internal) printf 'true\\n' ;;
  *) printf '\\n' ;;
esac
""",
        encoding="utf-8",
    )
    fake_gh.chmod(0o755)
    fake_sleep = fake_bin / "sleep"
    fake_sleep.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    fake_sleep.chmod(0o755)

    output = tmp_path / "github-output"
    script = _extract_run_block(
        WORKFLOW.read_text(encoding="utf-8"),
        "Resolve target repository visibility",
    )
    return subprocess.run(
        [bash],
        input=script,
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "TARGET_REPOSITORY": "ContextualWisdomLab/consumer",
            "EVENT_REPOSITORY_VISIBILITY": event_visibility,
            "FAKE_REPOSITORY_VISIBILITY": api_visibility,
            "FAKE_GH_LOG": str(gh_log),
            "GITHUB_OUTPUT": str(output),
        },
    )


@pytest.mark.parametrize(
    ("event_visibility", "expected_private"),
    [
        ("PUBLIC", "false"),
        ("public", "false"),
        ("PRIVATE", "true"),
        ("private", "true"),
        ("INTERNAL", "true"),
        ("internal", "true"),
    ],
)
def test_event_visibility_routes_without_api(
    tmp_path: Path,
    event_visibility: str,
    expected_private: str,
) -> None:
    result = _run_visibility_step(tmp_path, event_visibility)

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "github-output").read_text(encoding="utf-8") == (
        f"is_private={expected_private}\n"
    )
    assert not (tmp_path / "gh-log").exists()


@pytest.mark.parametrize(
    ("api_visibility", "expected_private"),
    [("public", "false"), ("private", "true"), ("internal", "true")],
)
def test_dispatch_api_visibility_preserves_internal_privacy(
    tmp_path: Path,
    api_visibility: str,
    expected_private: str,
) -> None:
    result = _run_visibility_step(
        tmp_path,
        "",
        api_visibility=api_visibility,
    )

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "github-output").read_text(encoding="utf-8") == (
        f"is_private={expected_private}\n"
    )
    gh_invocation = (tmp_path / "gh-log").read_text(encoding="utf-8")
    assert ".visibility" in gh_invocation
    assert ".private" not in gh_invocation


@pytest.mark.parametrize("event_visibility", ["unknown", "archived"])
def test_unknown_event_visibility_fails_closed(
    tmp_path: Path,
    event_visibility: str,
) -> None:
    result = _run_visibility_step(tmp_path, event_visibility)

    assert result.returncode != 0
    assert "was not public, private, or internal" in result.stdout
    assert not (tmp_path / "github-output").exists()
    assert not (tmp_path / "gh-log").exists()


def test_unknown_dispatch_api_visibility_fails_closed(tmp_path: Path) -> None:
    result = _run_visibility_step(tmp_path, "", api_visibility="unknown")

    assert result.returncode != 0
    assert "did not resolve to true or false" in result.stdout
    assert not (tmp_path / "github-output").exists()
