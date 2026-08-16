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
    """Require the central reviewer to consume Noema's stable data envelope."""
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    exchange = workflow_step(workflow, "Exchange Noema app token through OIDC")

    assert ".token // empty" not in exchange
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
