from pathlib import Path

from organization_commercial_readiness_fixtures import manual_workflow, workflow
from scripts.ci.organization_commercial_readiness_loop import (
    is_manual_product_entrypoint,
)


WORKFLOW_PATH = (
    Path(__file__).resolve().parents[1]
    / ".github"
    / "workflows"
    / "organization-commercial-readiness-loop.yml"
)


def test_product_entrypoint_rejects_missing_model_key_or_manual_trigger() -> None:
    """Both the NVIDIA model boundary and manual opt-in trigger are mandatory."""
    safe = manual_workflow()
    without_nvidia = (safe.content or "").replace(
        "NVIDIA_NIM_API_KEY", "OTHER_API_KEY"
    )
    without_dispatch = (safe.content or "").replace(
        "on:\n  workflow_dispatch:\n", "on:\n  push:\n"
    )

    assert not is_manual_product_entrypoint(workflow(content=without_nvidia))
    assert not is_manual_product_entrypoint(workflow(content=without_dispatch))


def test_json_receipt_is_retained_as_an_immutable_short_lived_artifact() -> None:
    """The machine-readable fleet receipt must outlive ephemeral runner storage."""
    source = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert (
        "uses: actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a"
        in source
    )
    assert "name: organization-commercial-readiness-${{ github.run_id }}-${{ github.run_attempt }}" in source
    assert "path: ${{ runner.temp }}/organization-commercial-readiness-loop.json" in source
    assert "if-no-files-found: error" in source
    assert "retention-days: 3" in source
    assert "results-receiver.actions.githubusercontent.com:443" in source
    assert "*.actions.githubusercontent.com:443" in source
    assert "*.blob.core.windows.net:443" in source
