"""Regression contract for organization required-workflow repository scope."""

from pathlib import Path

from scripts.ci.audit_central_required_workflows import EXPECTED_EXCLUSIONS


def test_rollout_scope_matches_canonical_exclusions() -> None:
    """Rollout prose must name every canonical exclusion and avoid universal claims."""
    rollout = Path("docs/org-required-workflow-rollout.md").read_text(encoding="utf-8")
    assert EXPECTED_EXCLUSIONS == {".github", "IRT-bibliography-set", "noema"}
    for repository in EXPECTED_EXCLUSIONS:
        assert f"`{repository}`" in rollout
    assert "all current and future organization\nrepositories inherit" not in rollout
    assert "outside that exclusion set inherits the nine central" in rollout


def test_doctoring_records_documentation_gate_closed() -> None:
    """Doctoring must describe the repaired documentation state, not an open gate."""
    doctoring = Path("docs/doctoring/code-scanning-required-workflow-audit.md").read_text(encoding="utf-8")
    assert "## Documentation reconciliation" in doctoring
    assert "## Outstanding documentation gate" not in doctoring
