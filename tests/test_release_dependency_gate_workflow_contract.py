"""Contract for the reusable pre-publish dependency gate workflow (issue #2342).

``origin/main`` had no fail-closed pre-publish gate: the only license signal was
``scripts/ci/sbom_inventory_aggregator.py``, a scheduled informational org SBOM
roll-up. This workflow is the gate a release workflow must call *before* it
publishes, and its outputs are exactly the inputs of
``.github/workflows/exact-artifact-sbom-attestation.yml`` so provenance covers
the bytes that were gated.
"""

from __future__ import annotations

import re
from pathlib import Path

_WORKFLOW = Path(".github/workflows/release-dependency-license-strix-gate.yml")
_ATTESTATION = Path(".github/workflows/exact-artifact-sbom-attestation.yml")

_HARDEN_RUNNER_PIN = "bf7454d06d71f1098171f2acdf0cd4708d7b5920"
_CHECKOUT_PIN = "9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0"
_SETUP_PYTHON_PIN = "5fda3b95a4ea91299a34e894583c3862153e4b97"
_UPLOAD_ARTIFACT_PIN = "043fb46d1a93c77aae656e7c1c64a875d1fc6a0a"
_DOWNLOAD_ARTIFACT_PIN = "3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c"


def _workflow_text() -> str:
    """Read the reusable pre-publish dependency gate workflow as UTF-8 text."""
    return _WORKFLOW.read_text(encoding="utf-8")


def _attestation_input_names() -> list[str]:
    """Return every required input name of the exact-artifact attestation workflow."""
    text = _ATTESTATION.read_text(encoding="utf-8")
    block = text.split("    inputs:\n", 1)[1].split("\npermissions:", 1)[0]
    return re.findall(r"(?m)^      ([a-z0-9_]+):$", block)


def test_workflow_is_reusable_and_never_branch_selectable() -> None:
    """The gate is `workflow_call` only, so no branch can select its code."""
    workflow = _workflow_text()
    assert "on:\n  workflow_call:\n" in workflow
    assert "workflow_dispatch:" not in workflow
    assert "pull_request" not in workflow
    assert "schedule:" not in workflow


def test_every_attestation_input_is_a_gate_output() -> None:
    """Composition is impossible unless the gate emits all 17 handoff fields."""
    workflow = _workflow_text()
    outputs = workflow.split("    outputs:\n", 1)[1].split("\npermissions:", 1)[0]
    declared = set(re.findall(r"(?m)^      ([a-z0-9_]+):$", outputs))
    assert set(_attestation_input_names()) == declared
    assert len(declared) == 17


def test_job_outputs_bind_the_sealing_and_upload_steps() -> None:
    """Each workflow output is wired to the seal step or the same-run artifact."""
    workflow = _workflow_text()
    job_outputs = workflow.split("    outputs:\n", 2)[2].split("    steps:", 1)[0]
    for name in _attestation_input_names():
        assert f"      {name}: " in job_outputs
    assert (
        "evidence_artifact_id: ${{ steps.sealed-evidence.outputs.artifact-id }}" in job_outputs
    )
    assert (
        "evidence_artifact_digest: sha256:"
        "${{ steps.sealed-evidence.outputs.artifact-digest }}" in job_outputs
    )


def test_gate_has_no_bypass_of_any_kind() -> None:
    """A fail-closed gate admits no continue-on-error, neutral, or always-run path."""
    workflow = _workflow_text()
    for forbidden in (
        "continue-on-error",
        "if: always()",
        "if: ${{ always() }}",
        "if: failure()",
        "if: ${{ failure() }}",
        "|| true",
        "exit 0",
        "--allow-failure",
    ):
        assert forbidden not in workflow, forbidden


def test_every_action_is_pinned_to_the_same_commits_as_attestation() -> None:
    """The gate and the attestation it feeds materialize identical trusted actions."""
    workflow = _workflow_text()
    attestation = _ATTESTATION.read_text(encoding="utf-8")
    for pin in (_HARDEN_RUNNER_PIN, _CHECKOUT_PIN, _UPLOAD_ARTIFACT_PIN, _DOWNLOAD_ARTIFACT_PIN):
        assert pin in workflow
        assert pin in attestation
    assert _SETUP_PYTHON_PIN in workflow
    references = re.findall(r"(?m)^ +uses: (.+)$", workflow)
    assert len(references) == 7
    for reference in references:
        assert re.match(r"^[^@]+@[0-9a-f]{40} # ", reference), reference


def test_permissions_are_read_only_at_workflow_and_job_scope() -> None:
    """The gate never needs write access; it only reads and uploads its evidence."""
    workflow = _workflow_text()
    assert "\npermissions:\n  contents: read\n" in workflow
    job = workflow.split("  gate:\n", 1)[1]
    assert "    permissions:\n      contents: read\n" in job
    for forbidden in ("contents: write", "id-token: write", "pull-requests: write"):
        assert forbidden not in workflow


def test_trusted_gate_is_materialized_from_this_repository_at_its_pinned_sha() -> None:
    """The decision code is the base repository's, never the caller's tree."""
    workflow = _workflow_text()
    assert "repository: ContextualWisdomLab/.github" in workflow
    assert "ref: ${{ github.workflow_sha }}" in workflow
    assert "path: trusted-gate" in workflow
    assert "persist-credentials: false" in workflow
    for member in (
        "scripts/ci/release_dependency_gate.py",
        "scripts/ci/release_dependency_capture_raw.sh",
        "scripts/ci/spdx_license_policy.py",
        "scripts/ci/strix_evidence_binding.py",
    ):
        assert member in workflow
    assert "sparse-checkout-cone-mode: false" in workflow


def test_gate_steps_run_only_the_trusted_materialized_code() -> None:
    """Every gate invocation is isolated and rooted in the trusted checkout."""
    workflow = _workflow_text()
    for invocation in re.findall(r"python3 [^\n]*release_dependency_gate\.py \w+", workflow):
        assert invocation.startswith(
            "python3 -I trusted-gate/scripts/ci/release_dependency_gate.py"
        ), invocation
    assert "bash trusted-gate/scripts/ci/release_dependency_capture_raw.sh" in workflow


def test_step_order_captures_then_strixes_then_gates_then_seals() -> None:
    """Sealing may only follow a passing gate, which may only follow Strix evidence."""
    workflow = _workflow_text()
    order = [
        "Harden runner",
        "Materialize immutable trusted gate",
        "Check out the exact release head",
        "Collect raw resolved-dependency evidence from both ecosystems",
        "Assemble per-dependency evidence and isolated synthetic fixtures",
        "Run Strix against one isolated synthetic fixture per dependency",
        "Refuse the release unless every dependency passes",
        "Seal exactly the gated bytes for attestation",
        "Export the sealed evidence as one immutable same-run artifact",
    ]
    positions = [workflow.index(marker) for marker in order]
    assert positions == sorted(positions), "gate steps are out of order"


def test_strix_uses_the_zero_cost_gateway_and_never_a_direct_provider() -> None:
    """Strix routes through the vendored orchestrator's fail-closed free pool."""
    workflow = _workflow_text()
    assert "STRIX_LLM: contextual-orchestrator/orchestrator/free" in workflow
    assert "scripts/ci/contextual_orchestrator_review_sidecar.sh" in workflow
    for secret in (
        "BYTEZ_API_KEY",
        "NVIDIA_NIM_API_KEY",
        "NVIDIA_NIM_API_KEY_SUB",
        "OPENROUTER_API_KEY",
        "OPENAI_API_KEY",
    ):
        assert f"{secret}: ${{{{ secrets.{secret} }}}}" in workflow
    assert "COPILOT_GITHUB_TOKEN" not in workflow


def test_strix_binding_is_written_with_the_structured_contract_only() -> None:
    """The binding the gate requires is emitted from machine-readable findings."""
    workflow = _workflow_text()
    assert 'schema: "cwl.release-dependency-strix-binding/1"' in workflow
    assert "vulnerabilities.json" in workflow
    assert "no_exploitable_findings" in workflow
    assert "findings_present" in workflow
    assert "STRIX_BINDING_MISSING" in workflow


def test_model_path_carries_no_elapsed_time_budget() -> None:
    """Per docs/product-goal-directive.md section 8, inference time is never capped."""
    workflow = _workflow_text()
    assert "timeout-minutes: 360" in workflow
    assert "timeout" not in workflow.replace("timeout-minutes: 360", "")
    assert "--timeout" not in workflow
