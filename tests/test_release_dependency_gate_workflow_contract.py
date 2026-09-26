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
import subprocess
from pathlib import Path

_WORKFLOW = Path(".github/workflows/release-dependency-license-strix-gate.yml")
_ATTESTATION = Path(".github/workflows/exact-artifact-sbom-attestation.yml")

_HARDEN_RUNNER_PIN = "bf7454d06d71f1098171f2acdf0cd4708d7b5920"
_CHECKOUT_PIN = "9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0"
_SETUP_PYTHON_PIN = "5fda3b95a4ea91299a34e894583c3862153e4b97"
_UPLOAD_ARTIFACT_PIN = "043fb46d1a93c77aae656e7c1c64a875d1fc6a0a"
_DOWNLOAD_ARTIFACT_PIN = "3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c"

# The five provider credentials the Strix stage needs and the licence stage does not.
_PROVIDER_SECRETS = (
    "BYTEZ_API_KEY",
    "NVIDIA_NIM_API_KEY",
    "NVIDIA_NIM_API_KEY_SUB",
    "OPENROUTER_API_KEY",
    "OPENAI_API_KEY",
)


def _workflow_text() -> str:
    """Read the reusable pre-publish dependency gate workflow as UTF-8 text."""
    return _WORKFLOW.read_text(encoding="utf-8")


def _job(name: str) -> str:
    match = re.search(rf"(?ms)^  {name}:\n(.*?)(?=^  [a-z]+:\n|\Z)", _workflow_text())
    assert match, name
    return match.group(1)


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
    assert declared == set(_attestation_input_names()) | {
        "full_set_verdict_artifact_id", "full_set_verdict_artifact_digest"
    }


def test_job_outputs_bind_the_sealing_and_upload_steps() -> None:
    """Each workflow output is wired to the seal step or the same-run artifact."""
    job_outputs = _job("gate").split("    outputs:\n", 1)[1].split("    steps:", 1)[0]
    for name in _attestation_input_names():
        assert f"      {name}: " in job_outputs
    assert (
        "evidence_artifact_id: ${{ steps.sealed-evidence.outputs.artifact-id }}" in job_outputs
    )
    assert (
        "evidence_artifact_digest: sha256:"
        "${{ steps.sealed-evidence.outputs.artifact-digest }}" in job_outputs
    )
    assert "full_set_verdict_artifact_id: ${{ steps.full-set-verdict.outputs.artifact-id }}" in job_outputs


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
    for pin in (_HARDEN_RUNNER_PIN, _CHECKOUT_PIN, _UPLOAD_ARTIFACT_PIN):
        assert pin in workflow
        assert pin in attestation
    assert _DOWNLOAD_ARTIFACT_PIN in attestation
    assert _SETUP_PYTHON_PIN in workflow
    references = re.findall(r"(?m)^ +uses: (.+)$", workflow)
    assert len(references) >= 7
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
    assert workflow.count("ref: e7755d9fed24a3e8a89d8ee5e1199f971c2189e6") == 3
    assert "path: trusted-gate" in workflow
    assert "persist-credentials: false" in workflow
    # The whole scripts/ci tree, because the trusted Strix gate, the
    # orchestrator sidecar and the token loader each source siblings by their
    # own directory; an enumerated file list breaks silently when one is added.
    assert "sparse-checkout: |\n            scripts/ci/\n" in workflow
    assert "requirements-strix-ci-hashes.txt" in workflow
    assert "sparse-checkout-cone-mode: false" in workflow


def test_gate_steps_run_only_the_trusted_materialized_code() -> None:
    """Every gate invocation is isolated and rooted in the trusted checkout."""
    workflow = _workflow_text()
    # `[\w-]+` and not `\w+`: the hyphenated subcommands (validate-inputs,
    # require-strix-credentials) must be pinned to the trusted checkout as well,
    # and `\w+` silently stopped at the first hyphen.
    invocations = re.findall(r"python3 [^\n]*release_dependency_gate\.py [\w-]+", workflow)
    for subcommand in (
        "validate-inputs",
        "capture",
        "prescreen",
        "require-strix-credentials",
        "fanout-plan",
        "seal",
    ):
        assert any(item.endswith(f" {subcommand}") for item in invocations), subcommand
    for invocation in invocations:
        assert invocation.startswith(
            "python3 -I trusted-gate/scripts/ci/release_dependency_gate.py"
        ), invocation
    assert "bash trusted-gate/scripts/ci/release_dependency_capture_raw.sh" in workflow
    assert "python3 -I trusted-gate/scripts/ci/collect_release_strix_bindings.py" in _job("gate")


def test_step_order_captures_then_strixes_then_gates_then_seals() -> None:
    """Sealing may only follow a passing gate, which may only follow Strix evidence."""
    prepare = _job("prepare")
    order = [
        "Harden runner",
        "Materialize immutable trusted gate",
        "Validate the exact release identity before anything else runs",
        "Check out the exact release head",
        "Verify every immutable distribution before dependency capture",
        "Collect the release closure without installing or executing it",
        "Assemble per-dependency evidence and isolated synthetic fixtures",
        "Refuse a denied or unverifiable licence before any credential exists",
        # Installing runs dependency code, so it may only follow the licence stage.
        "Install the prescreened closure into a lock-only environment",
        "Publish the exact licence-approved fixture matrix",
    ]
    assert [prepare.index(marker) for marker in order] == sorted(prepare.index(marker) for marker in order)
    matrix = _job("strix")
    assert "needs: prepare" in matrix
    assert matrix.index("Require every Strix provider credential") < matrix.index("Run Strix against this isolated synthetic fixture") < matrix.index("Upload this run-attempt binding")
    collector = _job("gate")
    assert "needs: [prepare, strix]" in collector
    assert collector.index("Recompute the exact licence-approved fixture matrix") < collector.index("Refuse unless every current-attempt binding") < collector.index("Seal exactly the gated bytes")


def test_matrix_and_collector_require_the_exact_attempt_set() -> None:
    prepare, matrix, collector = (_job(name) for name in ("prepare", "strix", "gate"))
    assert "matrix_json: ${{ steps.fanout.outputs.matrix_json }}" in prepare
    assert "matrix: ${{ fromJSON(needs.prepare.outputs.matrix_json) }}" in matrix
    assert "fail-fast: false" in matrix
    assert "max-parallel: 8" in matrix
    assert "name: ${{ matrix.artifact_name }}" in matrix
    assert "needs: [prepare, strix]" in collector
    assert "--run-attempt \"$GITHUB_RUN_ATTEMPT\"" in collector
    assert "--verified-distributions \"${RUNNER_TEMP}/verified-distributions.json\"" in collector
    assert "--verdict \"${RUNNER_TEMP}/full-set-verdict.json\"" in collector
    assert "id: full-set-verdict" in collector
    assert "${{ runner.temp }}/full-set-verdict.json\n            ${{ runner.temp }}/gate-report.json" in collector


def test_complete_distribution_set_is_required_and_verified_before_strix() -> None:
    workflow = _workflow_text()
    inputs = workflow.split("    inputs:\n", 1)[1].split("    secrets:\n", 1)[0]
    for name in ("distribution_set_artifact_id", "distribution_set_artifact_digest"):
        assert re.search(rf"(?m)^      {name}:\n(?:        .*\n)*?        required: true$", inputs)
    assert "build_artifact_id" not in inputs
    verifier = "python3 -I trusted-gate/scripts/ci/verify_release_distribution_set.py"
    assert verifier in workflow
    assert workflow.index(verifier) < workflow.index("release_dependency_gate.py prescreen")
    assert workflow.index(verifier) < workflow.index("secrets.BYTEZ_API_KEY")
    assert "--record-artifact-id \"$RECORD_ID\"" in workflow
    assert "--record-artifact-digest \"$RECORD_DIGEST\"" in workflow
    assert "--run-attempt \"$GITHUB_RUN_ATTEMPT\"" in workflow
    assert "--wheel-filename \"$WHEEL_FILENAME\"" in workflow
    assert "--sdist-filename \"$SDIST_FILENAME\"" in workflow


def test_the_licence_decision_precedes_every_credential_and_model_step() -> None:
    """A denied licence is refused before a provider secret is read at all.

    `capture` only assembles evidence and fixtures; it rejects no licence. The
    fail-closed licence determination therefore runs as its own step, ahead of the
    gateway, the Strix toolchain, the credential binding, and Strix itself.
    """
    workflow = _workflow_text()
    prepare = _job("prepare")
    matrix = _job("strix")
    assert "secrets." not in prepare
    assert "needs: prepare" in matrix
    prescreen = workflow.index("release_dependency_gate.py prescreen")
    for later in (
        "contextual_orchestrator_review_sidecar.sh",
        "load_contextual_orchestrator_token.sh",
        "Install the pinned Strix toolchain",
        "strix_quick_gate.sh",
        "python3 -I trusted-gate/scripts/ci/collect_release_strix_bindings.py",
    ):
        assert prescreen < workflow.index(later), later
    # The first mention of any provider secret must come after the licence stage.
    first_secret = min(
        workflow.index(f"secrets.{secret}") for secret in _PROVIDER_SECRETS
    )
    assert prescreen < first_secret


def test_the_exact_sha_shape_is_validated_before_any_credentialed_step() -> None:
    """An input typed only as `string` is shape-checked before the release is fetched."""
    workflow = _workflow_text()
    validate = workflow.index("release_dependency_gate.py validate-inputs")
    assert validate < workflow.index("Check out the exact release head")
    assert validate < workflow.index("release_dependency_gate.py prescreen")
    assert "--source-sha " in workflow
    assert "--source-repository " in workflow


def test_provider_secrets_are_optional_but_the_strix_stage_still_requires_them() -> None:
    """Optional secrets enable a credential-free licence run, never a skipped scan."""
    workflow = _workflow_text()
    block = workflow.split("    secrets:\n", 1)[1].split("    outputs:", 1)[0]
    for secret in _PROVIDER_SECRETS:
        assert f"      {secret}:\n        required: false\n" in block, secret
    assert "required: true" not in block
    # Absence is enforced by a command that fails, not by a condition that skips,
    # and that command runs the trusted checkout's code like every other stage.
    assert (
        "python3 -I trusted-gate/scripts/ci/release_dependency_gate.py "
        "require-strix-credentials" in workflow
    )
    assert "STRIX_CREDENTIALS_ABSENT" in workflow


def test_no_step_is_conditional_on_a_secret_being_present() -> None:
    """A secret-conditional `if:` would skip the scan instead of failing closed."""
    workflow = _workflow_text()
    for line in workflow.splitlines():
        stripped = line.strip()
        if stripped.startswith("if:"):
            assert "secrets." not in stripped, line
    # Secrets reach steps only as environment bindings, each binding its own name.
    for line in workflow.splitlines():
        if "secrets." in line:
            assert re.fullmatch(
                r"[A-Z0-9_]+: \$\{\{ secrets\.[A-Z0-9_]+ \}\}", line.strip()
            ), line


def test_failure_evidence_survives_the_failure_that_produced_it() -> None:
    """Each report uploads on failure too, bound to the step that writes it."""
    workflow = _workflow_text()
    for step_id, name in (
        ("license-stage", "release-dependency-license-report"),
        ("full-stage", "release-dependency-gate-report"),
    ):
        assert f"        id: {step_id}\n" in workflow
        condition = (
            f"        if: ${{{{ !cancelled() && steps.{step_id}.conclusion != 'skipped' }}}}\n"
        )
        assert condition in workflow, step_id
        assert (
            "          name: ${{ inputs.evidence_artifact_name == "
            "'release-dependency-sealed-evidence' && "
            f"'{name}' || format('{name}--{{0}}', inputs.evidence_artifact_name) }}}}\n"
        ) in workflow
    # A missing report stays a failure rather than being masked. Only executable
    # lines are counted; the prose above these steps names the setting too.
    executable = [
        line for line in workflow.splitlines() if not line.lstrip().startswith("#")
    ]
    assert sum("if-no-files-found: error" in line for line in executable) == 5
    # `always()` is forbidden outright by test_gate_has_no_bypass_of_any_kind; the
    # only conditions in this workflow are the two evidence-retention ones plus the
    # pre-existing lock-only install guard.
    conditions = [line.strip() for line in executable if line.strip().startswith("if:")]
    assert len(conditions) == 4


def _render_report_names(evidence_name: str) -> set[str]:
    """Check the shipped limited expression contract, then substitute its input.

    This is a static contract check, not a GitHub Actions expression runtime.
    Only ASCII fixtures are modeled: Actions string equality ignores case,
    while format preserves the supplied input's spelling.
    """
    assert evidence_name.isascii()
    expressions = re.findall(
        r"name: \$\{\{ inputs\.evidence_artifact_name == '([^']+)' && "
        r"'([^']+)' \|\| format\('([^']+)', inputs\.evidence_artifact_name\) \}\}",
        _workflow_text(),
    )
    assert len(expressions) == 2
    return {
        legacy if evidence_name.lower() == default.lower() else template.format(evidence_name)
        for default, legacy, template in expressions
    }


def test_repeated_calls_have_disjoint_diagnostic_artifact_names() -> None:
    """Two same-run legs retain both reports without reusing upload names."""
    first = _render_report_names("license-evidence-linux-py312")
    second = _render_report_names("license-evidence-windows-py314")
    assert len(first) == len(second) == 2
    assert first.isdisjoint(second)
    assert len(first | second | {
        "license-evidence-linux-py312", "license-evidence-windows-py314"
    }) == 6


def test_default_reports_keep_legacy_names_without_custom_call_collision() -> None:
    """Existing single-call consumers keep their names, even next to a custom leg."""
    default = "release-dependency-sealed-evidence"
    assert f"        default: {default}\n" in _workflow_text()
    legacy = _render_report_names(default)
    assert legacy == {"release-dependency-license-report", "release-dependency-gate-report"}
    for custom in ("release-dependency", "license-evidence-linux-py312"):
        assert legacy.isdisjoint(_render_report_names(custom))


def test_case_variants_of_default_are_not_distinct_report_names() -> None:
    """Case-only default variants share legacy names; callers must not mix them."""
    legacy = _render_report_names("release-dependency-sealed-evidence")
    for variant in (
        "RELEASE-DEPENDENCY-SEALED-EVIDENCE",
        "Release-Dependency-Sealed-Evidence",
    ):
        assert _render_report_names(variant) == legacy
        assert all("--" not in name for name in _render_report_names(variant))


def test_custom_names_preserve_spelling_and_require_caller_namespace() -> None:
    custom = "License-Evidence-Linux-Py312"
    assert _render_report_names(custom) == {
        f"release-dependency-license-report--{custom}",
        f"release-dependency-gate-report--{custom}",
    }
    # Arbitrary sealed names can still collide with another call's diagnostic
    # name. FMLS callers use the separate lowercase license-evidence-* prefix.
    lower_custom = "license-evidence-linux-py312"
    derived = f"release-dependency-license-report--{lower_custom}"
    assert derived in _render_report_names(lower_custom)
    assert not derived.startswith("license-evidence-")


def test_sealed_evidence_names_cannot_collide_with_diagnostic_artifacts() -> None:
    """Run the workflow's input guard against colliding same-run names."""
    workflow = _workflow_text()
    guard = 'case "$EVIDENCE_ARTIFACT_NAME" in' + workflow.split(
        'case "$EVIDENCE_ARTIFACT_NAME" in', 1
    )[1].split("esac", 1)[0] + "esac"
    assert workflow.index(guard) < workflow.index("release_dependency_gate.py validate-inputs")
    for name, allowed in (
        ("release-dependency-sealed-evidence", True),
        ("license-evidence-linux-py312", True),
        ("foo", False),
        ("release-dependency-license-report--foo", False),
        ("release-dependency-gate-report--foo", False),
        ("RELEASE-DEPENDENCY-SEALED-EVIDENCE", False),
    ):
        result = subprocess.run(
            ["bash", "-e", "-c", guard],
            env={"EVIDENCE_ARTIFACT_NAME": name},
            capture_output=True,
            text=True,
        )
        assert (result.returncode == 0) is allowed, (name, result.stderr)


def test_strix_uses_the_zero_cost_gateway_and_never_a_direct_provider() -> None:
    """Strix routes through the vendored orchestrator's fail-closed free pool."""
    workflow = _workflow_text()
    assert "printf '%s' 'orchestrator/free' > \"${RUNNER_TEMP}/strix_llm.txt\"" in workflow
    assert "STRIX_LLM_DEFAULT_PROVIDER: contextual_orchestrator" in workflow
    assert 'sidecar_base" != "http://127.0.0.1:18080"' in workflow
    assert "scripts/ci/contextual_orchestrator_review_sidecar.sh" in workflow
    assert "scripts/ci/load_contextual_orchestrator_token.sh" in workflow
    for secret in (
        "BYTEZ_API_KEY",
        "NVIDIA_NIM_API_KEY",
        "NVIDIA_NIM_API_KEY_SUB",
        "OPENROUTER_API_KEY",
        "OPENAI_API_KEY",
    ):
        assert f"{secret}: ${{{{ secrets.{secret} }}}}" in workflow
    assert "COPILOT_GITHUB_TOKEN" not in workflow


def test_strix_runs_through_the_trusted_gate_in_an_isolated_fixture_workspace() -> None:
    """Each fixture is scanned by the org's trusted Strix gate, one workspace each."""
    workflow = _workflow_text()
    assert 'bash "$trusted_gate_root/scripts/ci/strix_quick_gate.sh"' in workflow
    assert 'cd "$workspace" &&' in workflow
    assert 'STRIX_REPO_ROOT="$workspace"' in workflow
    assert 'workspace="${RUNNER_TEMP}/strix-workspace"' in workflow
    # The scanned directory holds the fixture only; the trusted binder the gate
    # requires at $STRIX_REPO_ROOT/scripts/ci sits beside it, never inside it.
    assert "STRIX_TARGET_PATH: fixture" in workflow
    assert 'printf \'%s\\n\' "$FIXTURE_JSON" > "$workspace/fixture/fixture.json"' in workflow
    assert 'IS_PR_EVIDENCE_RUN: "false"' in workflow
    # The trusted gate resolves its binder against STRIX_REPO_ROOT on current
    # main and against its own script directory once #2291 lands; the binder is
    # copied into each workspace so both resolutions hold without editing that
    # file, which #2291 owns.
    assert 'cp "$trusted_gate_root/scripts/ci/strix_evidence_binding.py" \\' in workflow
    assert '"$workspace/scripts/ci/strix_evidence_binding.py"' in workflow


def test_lock_only_environment_holds_only_the_prescreened_lock() -> None:
    """Lock/environment agreement is meaningless unless the env holds only the lock.

    The environment is created and installed into *after* the licence stage, by the
    trusted script's gated install mode, so the workflow names the interpreter and
    the collected root rather than running pip itself.
    """
    workflow = _workflow_text()
    assert 'python3 -m venv --without-pip "${RUNNER_TEMP}/gate-venv"' in workflow
    assert "--install-gated" in workflow
    assert '--python-interpreter "${RUNNER_TEMP}/gate-venv/bin/python"' in workflow
    assert '--license-report "${RUNNER_TEMP}/license-report.json"' in workflow
    # Collection and the gated install must share one download root, so the bytes
    # that were judged are the bytes that get installed.
    assert workflow.count('--download-root "${RUNNER_TEMP}/collected"') == 4


def test_strix_binding_is_written_with_the_structured_contract_only() -> None:
    """The binding the gate requires is emitted from machine-readable findings."""
    workflow = _workflow_text()
    assert 'schema: "cwl.release-dependency-strix-binding/1"' in workflow
    assert "vulnerabilities.json" in workflow
    assert "no_exploitable_findings" in workflow
    assert "findings_present" in workflow
    assert 'test -n "$vulnerabilities"' in workflow
    assert "collect_release_strix_bindings.py" in workflow


def test_model_path_carries_no_elapsed_time_budget() -> None:
    """Per docs/product-goal-directive.md section 8, inference time is never capped.

    `#1889`, `#1890`, and `#1892` each capped a model step and were all reverted.
    Every Strix timeout knob is therefore pinned to the unbounded value 0.
    """
    workflow = _workflow_text()
    for unbounded in (
        "export LLM_TIMEOUT=0",
        "export STRIX_MEMORY_COMPRESSOR_TIMEOUT=0",
        "export STRIX_PROCESS_TIMEOUT_SECONDS=0",
        "export STRIX_TOTAL_TIMEOUT_SECONDS=0",
    ):
        assert unbounded in workflow
    # Comments may name the trusted timeout-compat helpers; only executable
    # lines are scanned for an actual budget.
    remainder = "\n".join(
        line for line in workflow.splitlines() if not line.lstrip().startswith("#")
    )
    for allowed in (
        "timeout-minutes: 360",
        "timeout-minutes: 180",
        "export LLM_TIMEOUT=0",
        "export STRIX_MEMORY_COMPRESSOR_TIMEOUT=0",
        "export STRIX_PROCESS_TIMEOUT_SECONDS=0",
        "export STRIX_TOTAL_TIMEOUT_SECONDS=0",
    ):
        remainder = remainder.replace(allowed, "")
    assert "timeout" not in remainder.lower()
