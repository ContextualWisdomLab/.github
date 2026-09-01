"""Prevent mutation or credential regression in the lifecycle inventory."""

from pathlib import Path


def test_lifecycle_inventory_workflow_is_read_only_and_exact_head() -> None:
    """The integrated sweep publishes receipts without registry mutation."""
    text = Path(".github/workflows/workflow-lifecycle-inventory.yml").read_text()
    assert "contents: read" in text
    assert "actions: read" in text
    assert "persist-credentials: false" in text
    assert 'test "$(git rev-parse HEAD)" = "$GITHUB_SHA"' in text
    assert "--live" in text
    assert "--receipt-output" in text
    assert "retention-days: 30" in text
    assert "secrets: inherit" not in text
    assert "COPILOT_GITHUB_TOKEN" not in text
    assert "/disable" not in text
    assert "--mutate" not in text
