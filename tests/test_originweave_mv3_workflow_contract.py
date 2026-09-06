"""Contract for the centrally owned OriginWeave browser-evidence workflow."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "originweave-mv3-evidence.yml"


def test_originweave_mv3_workflow_is_pinned_sandboxed_and_least_privilege() -> None:
    """The owner workflow must verify artifacts and preserve Chromium sandboxing."""

    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "workflow_call:" in workflow
    assert "permissions:\n  contents: read" in workflow
    assert "ContextualWisdomLab/OriginWeave" in workflow
    assert "150.0.7871.129" in workflow
    assert "3c8aa248aab79834862fcdc7593181b82b9079feb4a192d9ca1855c576e50060" in workflow
    assert "eb71d98fc5415d03f02949cad0bf7b2eba02715ade6fbeedefcb4d783f7695f3" in workflow
    assert "sha256sum --check" in workflow
    assert "sudo chown root:root" in workflow
    assert "sudo chmod 4755" in workflow
    assert "CHROME_DEVEL_SANDBOX" in workflow
    assert "--no-sandbox" not in workflow
    assert "scripts/ci/run_mv3_compatibility.py" in workflow
    assert "secrets:" not in workflow
    assert "persist-credentials: false" in workflow
