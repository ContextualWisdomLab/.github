"""Coverage for scheduler workflow-starting credential invariants."""

import pytest

from scripts.ci import pr_review_merge_scheduler_core as scheduler_core


def test_withheld_mutation_reason_rejects_a_workflow_starting_credential(monkeypatch):
    """Withheld-mutation text cannot be fabricated for an accepted credential."""
    monkeypatch.setenv("SCHEDULER_MUTATION_TOKEN_SOURCE", "opencode-app")
    monkeypatch.setenv("GH_TOKEN", "selected-mutation-token")
    monkeypatch.setenv("SCHEDULER_WORKFLOW_TOKEN", "workflow-runner-token")

    with pytest.raises(RuntimeError, match="requires a non-triggering mutation credential"):
        scheduler_core.non_triggering_head_mutation_reason("update-branch")
