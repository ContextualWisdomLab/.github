"""Regression contracts for the Noema OIDC exchange consumer."""

import json
import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "noema-review.yml"


def workflow_step(workflow: str, name: str) -> str:
    """Return one named workflow step without parsing untrusted YAML tags."""
    marker = f"      - name: {name}\n"
    start = workflow.index(marker)
    try:
        end = workflow.index("\n      - name:", start + len(marker))
    except ValueError:
        end = len(workflow)
    return workflow[start:end]


def workflow_run_script(workflow: str, name: str) -> str:
    """Return the executable shell body from one named workflow step."""
    step = workflow_step(workflow, name)
    marker = "        run: |\n"
    body = step.split(marker, maxsplit=1)[1]
    return "\n".join(line.removeprefix("          ") for line in body.splitlines())


def run_exchange_script(
    tmp_path: Path, token_response: dict[str, object]
) -> subprocess.CompletedProcess[str]:
    """Execute the production exchange shell with a deterministic fake transport."""
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    script = workflow_run_script(workflow, "Exchange Noema app token through OIDC")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir(exist_ok=True)
    fake_curl = fake_bin / "curl"
    fake_curl.write_text(
        """#!/usr/bin/env python3
import os
import sys

if "audience=" in sys.argv[-1]:
    print('{"value":"synthetic-oidc-assertion"}')
else:
    print(os.environ["FAKE_TOKEN_RESPONSE"])
""",
        encoding="utf-8",
    )
    fake_curl.chmod(0o755)
    github_output = tmp_path / "github-output"
    github_output.unlink(missing_ok=True)
    environment = os.environ.copy()
    environment.update(
        {
            "PATH": f"{fake_bin}{os.pathsep}{environment['PATH']}",
            "ACTIONS_ID_TOKEN_REQUEST_TOKEN": "synthetic-request-token",
            "ACTIONS_ID_TOKEN_REQUEST_URL": "https://actions.invalid/id-token",
            "OIDC_AUDIENCE": "synthetic-noema-review",
            "TOKEN_EXCHANGE_URL": "https://noema.invalid/exchange",
            "TARGET_REPOSITORY": "ExampleOrg/example-repository",
            "GITHUB_WORKFLOW_REF": (
                "ExampleOrg/control-plane/.github/workflows/"
                "noema-review.yml@refs/heads/main"
            ),
            "GITHUB_OUTPUT": str(github_output),
            "FAKE_TOKEN_RESPONSE": json.dumps(token_response),
        }
    )
    return subprocess.run(
        ["bash", "-c", script],
        check=False,
        capture_output=True,
        env=environment,
        text=True,
    )


def test_oidc_exchange_consumes_noema_standard_success_envelope() -> None:
    """Require the central reviewer to consume Noema's stable data envelope."""
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    exchange = workflow_step(workflow, "Exchange Noema app token through OIDC")

    assert ".token // empty" not in exchange
    assert "Noema app token exchange unavailable: response envelope was invalid." in exchange
    assert 'if [ -z "${GITHUB_WORKFLOW_REF:-}" ]; then' in exchange
    assert '--arg target_repository "$TARGET_REPOSITORY"' in exchange
    assert '--arg workflow_ref "$GITHUB_WORKFLOW_REF"' in exchange
    assert ".ok == true" in exchange
    assert "(.data | type == \"object\")" in exchange
    assert '(.data.token | type == "string" and test("^[!-~]+\\\\z"))' in exchange
    assert ".data.repository == $target_repository" in exchange
    assert ".data.workflow_ref == $workflow_ref" in exchange
    assert "(.data.token_expires_at | type == \"string\" and length > 0)" in exchange
    assert "fromdateiso8601" in exchange
    assert "$expires_at > now" in exchange
    assert "(.trace_id | type == \"string\" and length > 0)" in exchange
    assert 'app_token="$(jq -r \'.data.token\' <<<"$token_response")"' in exchange


def test_oidc_exchange_keeps_token_out_of_diagnostics() -> None:
    """Require envelope failures to avoid reflecting raw credential material."""
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    exchange = workflow_step(workflow, "Exchange Noema app token through OIDC")

    assert 'echo "$token_response"' not in exchange
    assert 'printf "%s" "$token_response"' not in exchange
    mask = 'echo "::add-mask::$app_token"'
    output = 'echo "token=$app_token" >>"$GITHUB_OUTPUT"'
    assert mask in exchange
    assert output in exchange
    assert exchange.index(mask) < exchange.index(output)


def test_oidc_exchange_accepts_only_exact_live_producer_binding(tmp_path: Path) -> None:
    """Exercise the production shell against realistic valid and invalid envelopes."""
    repository = "ExampleOrg/example-repository"
    workflow_ref = (
        "ExampleOrg/control-plane/.github/workflows/"
        "noema-review.yml@refs/heads/main"
    )
    future_expiry = (datetime.now(UTC) + timedelta(hours=1)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    valid = {
        "ok": True,
        "data": {
            "token": "synthetic-app-token",
            "repository": repository,
            "workflow_ref": workflow_ref,
            "token_expires_at": future_expiry,
        },
        "trace_id": "synthetic-trace-id",
    }

    accepted = run_exchange_script(tmp_path, valid)

    assert accepted.returncode == 0, accepted.stdout + accepted.stderr
    assert "::add-mask::synthetic-app-token" in accepted.stdout
    assert (tmp_path / "github-output").read_text(encoding="utf-8") == (
        "token=synthetic-app-token\n"
    )

    invalid_responses = [
        {"ok": True, "token": "synthetic-app-token"},
        {**valid, "data": {**valid["data"], "repository": "ExampleOrg/other"}},
        {
            **valid,
            "data": {**valid["data"], "workflow_ref": "ExampleOrg/other/workflow"},
        },
        {
            **valid,
            "data": {
                **valid["data"],
                "token_expires_at": "2000-01-01T00:00:00Z",
            },
        },
        {**valid, "data": {**valid["data"], "token_expires_at": "not-a-time"}},
        {key: value for key, value in valid.items() if key != "trace_id"},
    ]
    invalid_responses.extend(
        {
            **valid,
            "data": {**valid["data"], "token": invalid_token},
        }
        for invalid_token in (
            " synthetic-app-token",
            "synthetic-app-token ",
            "synthetic-app-token\r",
            "synthetic-app-token\n",
            "synthetic-app-token\u00a0",
            "synthetic-app-token\u0001",
        )
    )

    for invalid in invalid_responses:
        rejected = run_exchange_script(tmp_path, invalid)
        diagnostic = rejected.stdout + rejected.stderr
        assert rejected.returncode != 0
        assert "response envelope was invalid" in diagnostic
        assert "synthetic-app-token" not in diagnostic
        assert not (tmp_path / "github-output").exists()
