"""Executable contract for the central SBOM inventory scheduler."""

from pathlib import Path
import os
import re
import subprocess
import textwrap

import pytest


WORKFLOW = Path(".github/workflows/sbom-inventory-scheduler.yml")


def _workflow_text() -> str:
    """Return the scheduler source as text for dependency-free contract checks."""
    return WORKFLOW.read_text(encoding="utf-8")


def _step_body(name: str) -> str:
    """Return one named executable workflow step, excluding later steps."""
    workflow = _workflow_text()
    marker = f"      - name: {name}\n"
    start = workflow.index(marker)
    next_step = workflow.find("\n      - name: ", start + len(marker))
    return workflow[start : next_step if next_step != -1 else len(workflow)]


def test_sbom_inventory_scheduler_runs_hourly() -> None:
    """Organization license evidence must refresh once each hour."""
    workflow = _workflow_text()
    assert 'cron: "0 * * * *"' in workflow
    assert 'cron: "0 6 * * 1"' not in workflow


def test_sbom_inventory_scheduler_requires_cross_repo_credential() -> None:
    """Repository-scoped github.token must never publish a partial org inventory."""
    workflow = _workflow_text()
    credential_step = _step_body("Require organization-wide SBOM credential")
    assert "|| github.token" not in workflow
    assert (
        "GH_TOKEN: ${{ secrets.SBOM_INVENTORY_TOKEN || steps.aggregator_app_token.outputs.token }}"
        in credential_step
    )
    assert 'if [ -z "${GH_TOKEN:-}" ]; then' in credential_step
    assert "refusing partial inventory" in credential_step
    assert "exit 1" in credential_step


def test_sbom_inventory_scheduler_excludes_forks_before_collection() -> None:
    """Only repositories proven non-forks may become owned inventory targets."""
    discovery_step = _step_body("Discover live non-fork repositories")
    aggregation_step = _step_body("Aggregate org SBOM inventory")
    assert "gh repo list" in discovery_step
    assert '"nameWithOwner,isFork"' in discovery_step
    assert ".[] | select(.isFork == false) | .nameWithOwner" in discovery_step
    assert "cwl-nonfork-repositories.txt" in discovery_step
    assert 'repo_args+=(--repo "$repo")' in aggregation_step
    assert '"${repo_args[@]}"' in aggregation_step
    assert '--org "$ORG_LOGIN"' not in aggregation_step


def test_sbom_inventory_scheduler_authenticates_git_before_publication() -> None:
    """The non-persistent checkout must establish Git auth before remote mutation."""
    publication_step = _step_body("Open or update inventory PR")
    auth_index = publication_step.index("gh auth setup-git")
    first_remote_index = min(
        publication_step.index("git ls-remote"),
        publication_step.index("git push"),
    )
    assert auth_index < first_remote_index


def test_sbom_inventory_scheduler_does_not_force_push() -> None:
    """Recurring publication must preserve concurrent branch history."""
    publication_step = _step_body("Open or update inventory PR")
    assert "--force" not in publication_step
    assert "--force-with-lease" not in publication_step


@pytest.mark.parametrize("dedicated,app_token,expected_calls,expected_exit", [
    ("fixture-dedicated", "fixture-app", 0, 0),
    ("", "fixture-app", 2, 0),
    ("", "", 2, 1),
])
def test_sbom_token_exchange_selection(tmp_path, dedicated, app_token, expected_calls, expected_exit):
    """Run real exchange and credential shells with local-only request fixtures."""
    workflow = _workflow_text()
    exchange = _step_body("Exchange OpenCode app token for cross-repo reads")
    credential = _step_body("Require organization-wide SBOM credential")
    # Pin the real job-env binding and parse only the supported step condition.
    job_env = workflow.split("    env:\n", 1)[1].split("    steps:\n", 1)[0]
    condition = re.search(r"^        if: (.+)$", exchange, re.MULTILINE)
    should_exchange = True
    if condition:
        assert "SBOM_TOKEN_CONFIGURED: ${{ secrets.SBOM_INVENTORY_TOKEN != '' }}" in job_env
        assert condition[1] == "env.SBOM_TOKEN_CONFIGURED != 'true'"
        should_exchange = not bool(dedicated)
    assert "GH_TOKEN: ${{ secrets.SBOM_INVENTORY_TOKEN || steps.aggregator_app_token.outputs.token }}" in credential
    output = tmp_path / "output"
    calls = tmp_path / "calls"
    env = {
        "PATH": os.environ["PATH"], "GITHUB_OUTPUT": str(output),
        "MOCK_CALLS": str(calls), "MOCK_APP_TOKEN": app_token,
        "ACTIONS_ID_TOKEN_REQUEST_TOKEN": "fixture-request",
        "ACTIONS_ID_TOKEN_REQUEST_URL": "https://fixture.invalid/oidc",
        "OIDC_AUDIENCE": "opencode-github-action",
        "OPENCODE_API_BASE_URL": "https://fixture.invalid",
    }
    mock = '''
curl() {
  printf 'request\\n' >> "$MOCK_CALLS"
  case "${@: -1}" in
    'https://fixture.invalid/oidc?audience=opencode-github-action')
      printf '%s' '{"value":"fixture-oidc"}' ;;
    'https://fixture.invalid/exchange_github_app_token')
      printf '{"token":"%s"}' "$MOCK_APP_TOKEN" ;;
    *) return 97 ;;
  esac
}
'''
    if should_exchange:
        result = subprocess.run(
            ["bash", "-c", textwrap.dedent(mock) + textwrap.dedent(exchange.split("        run: |\n", 1)[1])],
            env=env, capture_output=True, text=True, check=False,
        )
        assert result.returncode == 0, result.stderr
    outputs = dict(line.split("=", 1) for line in output.read_text().splitlines()) if output.exists() else {}
    env["GH_TOKEN"] = dedicated or outputs.get("token", "")
    result = subprocess.run(
        ["bash", "-c", textwrap.dedent(credential.split("        run: |\n", 1)[1])],
        env=env, capture_output=True, text=True, check=False,
    )
    assert result.returncode == expected_exit
    assert (len(calls.read_text().splitlines()) if calls.exists() else 0) == expected_calls
    if expected_exit:
        assert "refusing partial inventory" in result.stderr
