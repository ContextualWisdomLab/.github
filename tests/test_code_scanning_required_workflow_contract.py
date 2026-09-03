"""Regression contract for organization-required code-scanning workflows."""

from scripts.ci import audit_central_required_workflows as audit


_REQUIRED_CODE_SCANNING_WORKFLOW_PATHS = {
    ".github/workflows/scorecard-pr.yml",
    ".github/workflows/osv-scanner-pr.yml",
}


def test_ruleset_audit_requires_every_code_scanning_workflow() -> None:
    """The central audit must fail if either live code-scanning requirement disappears."""
    assert _REQUIRED_CODE_SCANNING_WORKFLOW_PATHS <= set(audit.REQUIRED_WORKFLOW_PATHS)


def test_ruleset_audit_deliberately_excludes_codeql_pr() -> None:
    """codeql-pr.yml must stay out of the required set (github/codeql-action cannot

    run inside a ruleset-required workflow -- see the 2026-09-03 correction in
    docs/org-required-workflow-rollout.md). A re-add here would silently
    re-introduce the 100% startup_failure regression the removal fixed.
    """
    assert ".github/workflows/codeql-pr.yml" not in audit.REQUIRED_WORKFLOW_PATHS
