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


def test_oidc_exchange_consumes_noema_standard_success_envelope() -> None:
    """The central reviewer must read the repository token from ``data``.

    Noema's stable success contract is ``{ok: true, data: {token, ...}}``. A
    top-level ``.token`` lookup silently turns a successful exchange into an
    empty credential and makes every OIDC-backed central review fail after the
    token was already minted. The consumer must authenticate the complete
    envelope and bind it to the requested repository before extracting the
    short-lived token.
    """
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    exchange = workflow_step(workflow, "Exchange Noema app token through OIDC")

    assert 'jq -r ".token // empty"' not in exchange
    assert "Noema app token exchange unavailable: response envelope was invalid." in exchange
    assert 'jq -e --arg target_repository "$TARGET_REPOSITORY"' in exchange
    assert ".ok == true" in exchange
    assert "(.data | type == \"object\")" in exchange
    assert "(.data.token | type == \"string\" and length > 0)" in exchange
    assert ".data.repository == $target_repository" in exchange
    assert "(.data.workflow_ref | type == \"string\" and length > 0)" in exchange
    assert "(.data.token_expires_at | type == \"string\" and length > 0)" in exchange
    assert 'app_token="$(jq -r \'.data.token\' <<<"$token_response")"' in exchange


def test_oidc_exchange_keeps_token_out_of_diagnostics() -> None:
    """Envelope failures may identify fields but must never reflect credentials."""
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    exchange = workflow_step(workflow, "Exchange Noema app token through OIDC")

    assert 'echo "$token_response"' not in exchange
    assert 'printf "%s" "$token_response"' not in exchange
    assert 'echo "::add-mask::$app_token"' in exchange
    assert 'echo "token=$app_token" >>"$GITHUB_OUTPUT"' in exchange
