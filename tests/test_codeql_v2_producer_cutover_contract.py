"""Regression contract for the versioned CodeQL producer cutover."""

from pathlib import Path


_WORKFLOW = Path(__file__).parents[1] / ".github" / "workflows" / "codeql-pr.yml"


def test_required_codeql_producer_uses_v2_head_envelope() -> None:
    """Require the protected v2 handler envelope instead of legacy dispatch."""

    source = _WORKFLOW.read_text(encoding="utf-8")

    assert '{event_type:"codeql-scan-v2"' in source
    assert 'pr_head:{schema:"1",ref:$pr_head_ref,sha:$pr_head_sha}' in source
    assert '{event_type:"codeql-scan",' not in source
