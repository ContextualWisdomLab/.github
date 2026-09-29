"""Noema review targets any owner that installed the App, not a fixed organization."""

from pathlib import Path
import re

WORKFLOW = Path(".github/workflows/noema-review.yml")


def test_target_owner_is_not_a_fixed_organization() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    # The workflow's own identity stays pinned; only targets are opened up.
    assert "^ContextualWisdomLab/[A-Za-z0-9_.-]+$" not in workflow
    assert "owner: ContextualWisdomLab" not in workflow
    assert 'if trusted_repository != "ContextualWisdomLab/.github":' in workflow
    pattern = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]+$")
    assert "^[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]+$" in workflow
    assert pattern.match("HYOSUNG-ITX-AI-Business-Department/llm-gateway-console")
    assert not pattern.match("-bad/owner")
    assert not pattern.match("owner/with/extra")


def test_every_app_token_owner_comes_from_the_validated_target() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    owners = re.findall(r"^\s+owner: (.+)$", workflow, re.MULTILINE)
    assert owners and set(owners) <= {
        "${{ steps.noema_metadata_credential.outputs.owner }}",
        "${{ steps.noema_credential.outputs.owner }}",
    }
    assert workflow.count('echo "owner=${TARGET_REPOSITORY%%/*}" >>"$GITHUB_OUTPUT"') == 3


def test_other_organizations_can_call_the_central_review() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    triggers = workflow.split("\nconcurrency:", 1)[0]
    assert "\n  workflow_call:\n" in triggers
    assert "\n  pull_request_target:\n" in triggers
