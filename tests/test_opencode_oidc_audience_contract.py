"""Regression contract for the Required OpenCode OIDC audience binding."""

from pathlib import Path


WORKFLOW = Path(".github/workflows/opencode-review.yml")


def test_opencode_dispatch_uses_declared_oidc_audience_variable() -> None:
    """The dispatch token request must use the declared ``OIDC_AUDIENCE`` name."""
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "audience=${OIDC_AUDIENCE}" in workflow
    assert "OIDIDC_AUDIENCE" not in workflow
