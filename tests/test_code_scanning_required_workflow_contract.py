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


def test_superseded_standalone_pr_scanners_are_removed() -> None:
    """Do not recreate duplicate PR runs after the ruleset migration."""
    for workflow_path in _SUPPLEMENTAL_CODE_SCANNING_WORKFLOW_PATHS:
        assert not (REPOSITORY_ROOT / workflow_path).exists()


def test_consolidated_security_scan_preserves_osv_and_scorecard_evidence() -> None:
    """The sole required owner must retain both scanners and their SARIF uploads."""
    workflow = (
        REPOSITORY_ROOT / ".github/workflows/security-scan.yml"
    ).read_text(encoding="utf-8")

    assert "  osv-scan:" in workflow
    assert "  scorecard:" in workflow
    assert "Upload OSV SARIF to code scanning" in workflow
    assert "Upload Scorecard SARIF to code scanning" in workflow


def test_ruleset_requires_dispatch_safe_codeql_pr() -> None:
    """Restore the central gate without reintroducing forbidden CodeQL actions."""
    workflow_path = ".github/workflows/codeql-pr.yml"
    workflow = (REPOSITORY_ROOT / workflow_path).read_text(encoding="utf-8")

    assert workflow_path in audit.REQUIRED_WORKFLOW_PATHS
    assert "uses: github/codeql-action" not in workflow
    assert "event_type:\"codeql-scan\"" in workflow
