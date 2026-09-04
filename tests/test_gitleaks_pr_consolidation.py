"""Contracts for consolidating the central repository's PR Gitleaks scan."""

from pathlib import Path
import re


WORKFLOWS = Path(__file__).parents[1] / ".github/workflows"


def _workflow(filename: str) -> str:
    return (WORKFLOWS / filename).read_text(encoding="utf-8")


def _on_block(workflow: str) -> str:
    match = re.search(r"(?m)^on:\n((?:.*\n)*?)(?=^\S|\Z)", workflow)
    assert match
    return match.group(1)


def _gitleaks_job(workflow: str) -> str:
    return workflow.split("  gitleaks:\n", 1)[1].split("\n  trivy-fs:", 1)[0]


def test_secret_scan_keeps_only_non_pr_backstops() -> None:
    """The standalone workflow retains every non-PR Gitleaks entry point."""
    trigger = _on_block(_workflow("secret-scan.yml"))

    assert "pull_request:" not in trigger
    assert "push:" in trigger
    assert "schedule:" in trigger
    assert 'types: [secret-scan]' in trigger


def test_security_scan_owns_the_fail_closed_pr_gitleaks_job() -> None:
    """The required bundle preserves the central PR Gitleaks hard gate."""
    workflow = _workflow("security-scan.yml")
    job = _gitleaks_job(workflow)

    assert "needs: changed-scope" not in job
    assert "github.event.action != 'closed'" in job
    assert "github.repository == 'ContextualWisdomLab/.github'" in job
    assert 'GITLEAKS_VERSION: "8.30.1"' in job
    assert 'GITLEAKS_SHA256: "551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb"' in job
    assert 'log_opts="${BASE_SHA}..${HEAD_SHA}"' in job
    assert '--log-opts="${log_opts}"' in job
    assert "gitleaks-results.upload.sarif" in job
    assert "github/codeql-action/upload-sarif@cdf488f595d80d6e07e03d4674febd5ab45fa938 # v4.37.9" in job
    assert "if: steps.gitleaks.outputs.rc != '0'" in job
    assert "exit 1" in job


def test_document_only_prs_still_admit_gitleaks() -> None:
    """Gitleaks remains independent from the document-only changed-scope gate."""
    workflow = _workflow("security-scan.yml")
    job = _gitleaks_job(workflow)

    assert "needs.changed-scope.outputs" not in job
    assert "*.md" not in job
