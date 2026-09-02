"""Contracts for retiring legacy hourly review-repair workflow identities."""

from __future__ import annotations

from pathlib import Path


_WORKFLOW = Path(".github/workflows/hourly-review-repair-registry-retirement.yml")
_REPLACEMENT = ".github/workflows/hourly-review-repair.yml"
_LEGACY_PATHS = (
    ".github/workflows/accounting-information-platform-hourly-review-repair.yml",
    ".github/workflows/afipc-hourly-review-repair.yml",
    ".github/workflows/bandscope-hourly-review-repair.yml",
    ".github/workflows/clearfolio-hourly-review-repair.yml",
    ".github/workflows/contextual-orchestrator-hourly-review-repair.yml",
    ".github/workflows/disksage-hourly-review-repair.yml",
    ".github/workflows/fast-mlsirm-hourly-review-repair.yml",
    ".github/workflows/github-hourly-review-repair.yml",
    ".github/workflows/governance-risk-compliance-hourly-review-repair.yml",
    ".github/workflows/inkspan-hourly-review-repair.yml",
    ".github/workflows/lineageweave-hourly-review-repair.yml",
    ".github/workflows/metering-billing-platform-hourly-review-repair.yml",
    ".github/workflows/nonnest2-hourly-review-repair.yml",
    ".github/workflows/orgmetra-hourly-review-repair.yml",
    ".github/workflows/originweave-hourly-review-repair.yml",
    ".github/workflows/psychometrics-commons-hourly-review-repair.yml",
    ".github/workflows/quarantine-sandbox-hourly-review-repair.yml",
    ".github/workflows/semantic-data-portal-hourly-review-repair.yml",
)


def _text() -> str:
    """Return the one-shot registry-retirement workflow source."""
    return _WORKFLOW.read_text(encoding="utf-8")


def test_retirement_is_not_another_scheduled_writer() -> None:
    """The migration can run on protected-main activation but owns no cadence."""
    text = _text()

    assert "  schedule:" not in text
    assert "  push:" in text
    assert "      - main" in text
    assert "  workflow_dispatch:" in text
    assert "actions: write" in text
    assert "contents: read" in text
    assert "contents: write" not in text
    assert "id-token: write" not in text


def test_retirement_names_every_legacy_identity_exactly_once() -> None:
    """No deleted hourly caller can remain an untracked active registry ID."""
    text = _text()

    assert len(_LEGACY_PATHS) == 18
    for path in _LEGACY_PATHS:
        assert text.count(f'"{path}"') == 1
    assert text.count(f"REPLACEMENT_PATH: {_REPLACEMENT}") == 1


def test_replacement_is_proven_active_before_any_disable_call() -> None:
    """The migration fails closed unless the consolidated scheduler is active."""
    text = _text()
    replacement_guard = 'if [[ "$replacement_state" != "active" ]]'
    disable_endpoint = '/actions/workflows/${workflow_id}/disable'

    assert replacement_guard in text
    assert disable_endpoint in text
    assert text.index(replacement_guard) < text.index(disable_endpoint)
    assert "Expected exactly one workflow registry identity" in text


def test_every_disabled_identity_is_read_back_and_verified() -> None:
    """A successful mutation is not evidence until the registry state is re-read."""
    text = _text()

    assert (
        "gh api \"/repos/${REPOSITORY}/actions/workflows/${workflow_id}\" --jq '.state'"
        in text
    )
    assert 'if [[ "$state" != "disabled_manually" ]]' in text
    assert 'disable_and_verify "$SELF_PATH"' in text
    assert text.rindex('disable_and_verify "$SELF_PATH"') > text.rindex(
        'for path in "${legacy_paths[@]}"'
    )


def test_retirement_does_not_expose_reviewer_or_provider_credentials() -> None:
    """Registry mutation uses only the scoped GitHub token and no model secrets."""
    text = _text()

    assert "GH_TOKEN: ${{ github.token }}" in text
    for forbidden in (
        "PR_REVIEW_MERGE_TOKEN",
        "OPENCODE_APPROVE_TOKEN",
        "COPILOT_GITHUB_TOKEN",
        "OPENAI_API_KEY",
        "OPENROUTER_API_KEY",
        "NVIDIA_NIM_API_KEY",
        "BYTEZ_API_KEY",
        "actions/checkout",
    ):
        assert forbidden not in text
