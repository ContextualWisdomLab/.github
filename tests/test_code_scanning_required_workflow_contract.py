"""Regression contract for the consolidated organization security scan."""

from pathlib import Path

from scripts.ci import audit_central_required_workflows as audit


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_SUPPLEMENTAL_CODE_SCANNING_WORKFLOW_PATHS = {
    ".github/workflows/scorecard-pr.yml",
    ".github/workflows/osv-scanner-pr.yml",
}


def test_ruleset_requires_only_the_consolidated_security_scan() -> None:
    """Do not inject duplicate OSV and Scorecard runs into every repository PR."""
    required_paths = set(audit.REQUIRED_WORKFLOW_PATHS)

    assert ".github/workflows/security-scan.yml" in required_paths
    assert _SUPPLEMENTAL_CODE_SCANNING_WORKFLOW_PATHS.isdisjoint(required_paths)


def test_consolidated_security_scan_preserves_osv_and_scorecard_evidence() -> None:
    """The sole required owner must retain both scanners and their SARIF uploads."""
    workflow = (
        REPOSITORY_ROOT / ".github/workflows/security-scan.yml"
    ).read_text(encoding="utf-8")

    assert "  osv-scan:" in workflow
    assert "  scorecard:" in workflow
    assert "Upload OSV SARIF to code scanning" in workflow
    assert "Upload Scorecard SARIF to code scanning" in workflow


def test_ruleset_audit_deliberately_excludes_codeql_pr() -> None:
    """codeql-pr.yml must stay out of the required set (github/codeql-action cannot

    run inside a ruleset-required workflow -- see the 2026-09-03 correction in
    docs/org-required-workflow-rollout.md). A re-add here would silently
    re-introduce the 100% startup_failure regression the removal fixed.
    """
    assert ".github/workflows/codeql-pr.yml" not in audit.REQUIRED_WORKFLOW_PATHS
