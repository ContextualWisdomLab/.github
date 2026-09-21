"""Contract tests separating gateway routing, tooling, and dispatch failures.

Three distinct failure classes were collapsed into one "provider unavailable"
reading during the 2026-09-21 review outage:

* OpenCode reached the vendored gateway but posted to an unprefixed path,
  so the gateway answered ``route_not_found`` and OpenCode surfaced its
  message verbatim as ``Error: not found``. The provider credentials were
  healthy throughout.
* Strix emitted Caido GraphQL tooling errors alongside genuine provider
  rate limits, and the workflow reported only the provider class.
* OpenCode Review Dispatch rejected a repository_dispatch before the
  sidecar existed, which is neither a gateway nor a provider outcome.

These contracts keep each class independently observable.
"""

from __future__ import annotations

import json
from pathlib import Path
import re

_ORG_REPO_ROOT = Path(__file__).resolve().parents[1]

AUTOFIX_WORKFLOW = _ORG_REPO_ROOT / ".github/workflows/pr-review-autofix.yml"
OPENCODE_DISPATCH_WORKFLOW = (
    _ORG_REPO_ROOT / ".github/workflows/opencode-review-dispatch.yml"
)
STRIX_WORKFLOW = _ORG_REPO_ROOT / ".github/workflows/strix.yml"
OPENCODE_CONFIG = _ORG_REPO_ROOT / "opencode.jsonc"

GATEWAY_SERVED_CHAT_PATH = "/v1/chat/completions"
EXPECTED_BASE_URL = "{env:CONTEXTUAL_ORCHESTRATOR_BASE_URL}/v1"


def _read(path: Path) -> str:
    """Return one tracked contract file as UTF-8 text."""
    return path.read_text(encoding="utf-8")


def _generated_opencode_configs(workflow_text: str) -> list[dict]:
    """Return every ``jq -n`` generated OpenCode config in one workflow."""
    matches = re.findall(
        r"jq -n(?:[^']*)'(\{.*?\})' >\"\$\{[A-Z_]+\}/opencode\.jsonc\"",
        workflow_text,
        re.DOTALL,
    )
    return [json.loads(match) for match in matches]


def _strip_jsonc_comments(text: str) -> str:
    """Drop ``//`` line comments so a JSONC config parses as JSON."""
    return "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("//")
    )


def test_autofix_opencode_provider_targets_the_served_gateway_path() -> None:
    """The autofix provider baseURL must resolve to the gateway's /v1 routes."""
    configs = _generated_opencode_configs(_read(AUTOFIX_WORKFLOW))
    assert configs, "no generated OpenCode config found in the autofix workflow"
    for config in configs:
        options = config["provider"]["contextual-orchestrator"]["options"]
        assert options["baseURL"] == EXPECTED_BASE_URL


def test_dispatch_opencode_provider_targets_the_served_gateway_path() -> None:
    """The dispatch gateway overlay must carry the same /v1 prefix.

    The dispatch workflow writes a provider-free base config and then layers
    the gateway provider on with a second ``jq`` filter, so the assertion is
    on every ``baseURL`` the workflow binds for that provider.
    """
    workflow = _read(OPENCODE_DISPATCH_WORKFLOW)
    bound = re.findall(
        r'"baseURL": "(\{env:CONTEXTUAL_ORCHESTRATOR_BASE_URL\}[^"]*)"', workflow
    )
    assert bound, "the dispatch workflow binds no gateway baseURL"
    assert set(bound) == {EXPECTED_BASE_URL}


def test_repository_opencode_config_targets_the_served_gateway_path() -> None:
    """The tracked reviewer config must not drop the gateway's /v1 prefix."""
    config = json.loads(_strip_jsonc_comments(_read(OPENCODE_CONFIG)))
    options = config["provider"]["contextual-orchestrator"]["options"]
    assert options["baseURL"] == EXPECTED_BASE_URL


def test_strix_reports_caido_tooling_failures_as_their_own_class() -> None:
    """Caido GraphQL breakage must not be reported only as a provider outage."""
    workflow = _read(STRIX_WORKFLOW)
    assert "tooling_error_signal=" in workflow
    for signature in (
        "Invalid HTTPQL query",
        "Failed to parse cursor",
        "TransportQueryError",
    ):
        assert signature in workflow
    assert "STRIX_TOOLING_ERROR" in workflow
    tooling_index = workflow.index("STRIX_TOOLING_ERROR")
    provider_index = workflow.index("STRIX_PROVIDER_UNAVAILABLE::Strix could not")
    assert tooling_index < provider_index, (
        "the tooling class must be emitted before the provider verdict so a "
        "scanner defect is never filed only as a provider outage"
    )


def test_dispatch_admission_failures_are_not_provider_failures() -> None:
    """Dispatch admission rejections must stay outside the provider vocabulary."""
    workflow = _read(OPENCODE_DISPATCH_WORKFLOW)
    admission_messages = (
        "repository_dispatch authorization rejected",
        "repository_dispatch metadata does not match the live pull request",
    )
    for message in admission_messages:
        assert message in workflow
        line = next(
            candidate
            for candidate in workflow.splitlines()
            if message in candidate
        )
        assert "provider" not in line.lower()
        assert "orchestrator" not in line.lower()
    sidecar_index = workflow.index("Provision contextual-orchestrator review sidecar")
    for message in admission_messages:
        assert workflow.index(message) < sidecar_index, (
            "dispatch admission runs before any sidecar exists, so its failure "
            "cannot be attributed to the gateway or a provider"
        )
