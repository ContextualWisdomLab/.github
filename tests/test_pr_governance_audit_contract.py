from pathlib import Path


def test_html4tree_public_fork_queue_requires_central_review_gate():
    """Guard the html4tree onboarding gap documented by the live audit."""
    audit = Path("PR_GOVERNANCE_AUDIT.md").read_text(encoding="utf-8")

    assert "html4tree" in audit
    assert "Do not leave an active public fork PR queue in the inventory-only state." in audit
    assert "organization required-workflow ruleset" in audit
    assert "temporary thin caller" in audit
    assert "same-head central review evidence" in audit
    assert "2026-06-29 KST `html4tree` onboarding gap" in audit
    assert "PR #3 is the lowest open PR" in audit
    assert "has no check runs and no reviews" in audit
    assert "do not bypass the review gate" in audit


def test_afipc_queue_has_central_required_workflow_evidence():
    """Guard the closed aFIPC central required-workflow fixture."""
    audit = Path("PR_GOVERNANCE_AUDIT.md").read_text(encoding="utf-8")
    rollout = Path("docs/org-required-workflow-rollout.md").read_text(
        encoding="utf-8"
    )

    assert "aFIPC" in audit
    assert "aFIPC" in rollout
    assert "PR #78" in audit
    assert "PR `#78` is no longer a target-coverage gap" in rollout
    assert "closed target-coverage fixture" in audit
    assert "b1ddafced86302f461e95259699f1efde5ec87c9" in audit


def test_new_public_nonfork_repos_are_classified_in_rollout_inventory():
    """Guard newly discovered public non-fork repository classification."""
    audit = Path("PR_GOVERNANCE_AUDIT.md").read_text(encoding="utf-8")
    rollout = Path("docs/org-required-workflow-rollout.md").read_text(
        encoding="utf-8"
    )

    for document in (audit, rollout):
        assert "17 public non-fork repositories" in document
        assert "kaefa" in document
        assert "waf-ids-ai-soc" in document

    assert "current PR #60 lacked central check runs" in rollout
    assert "runtime proof gap" in audit
    assert "PR #6 merged after central workflow proof" in rollout
    assert "PR #8 is now the open current-head runtime proof fixture" in rollout
    assert "43b62b5f347d1532c81b5ae38d8e41b4494fd486" in audit
    assert "48d8b56a0f995829fc95de4fed129d1c33aaadff" in audit
