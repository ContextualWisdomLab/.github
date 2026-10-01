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


def test_unfiltered_triggers_do_not_overclaim_stacked_ruleset_coverage() -> None:
    """Workflow triggers must not be presented as widening ruleset ref scope."""
    rollout = Path("docs/org-required-workflow-rollout.md").read_text(encoding="utf-8")
    workflows = {
        name: Path(f".github/workflows/{name}").read_text(encoding="utf-8")
        for name in ("security-scan.yml", "sast-semgrep.yml", "codeql-pr.yml")
    }
    rollout_words = " ".join(rollout.split())

    assert "They therefore also run for stacked pull requests" not in rollout
    assert "does not widen ruleset `18156473`" in rollout
    assert "do not materialize these required workflows" in rollout_words

    assert "stacked PRs must receive the same" not in workflows["security-scan.yml"]
    assert "Scan every PR base ref" not in workflows["sast-semgrep.yml"]
    assert "would also block coverage for\n    # stacked PRs" not in workflows["codeql-pr.yml"]
    for workflow in workflows.values():
        workflow_words = " ".join(workflow.replace("#", "").split())
        assert "does not widen ruleset 18156473" in workflow_words
