"""Regression contract for organization-required code-scanning workflows."""

from scripts.ci import audit_central_required_workflows as audit


_REQUIRED_CODE_SCANNING_WORKFLOW_PATHS = {
    ".github/workflows/codeql-pr.yml",
    ".github/workflows/scorecard-pr.yml",
    ".github/workflows/osv-scanner-pr.yml",
}


def test_ruleset_audit_requires_every_code_scanning_workflow() -> None:
    """The central audit must fail if any live code-scanning requirement disappears."""
    assert _REQUIRED_CODE_SCANNING_WORKFLOW_PATHS <= set(audit.REQUIRED_WORKFLOW_PATHS)
