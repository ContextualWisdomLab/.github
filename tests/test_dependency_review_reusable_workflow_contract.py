"""Contract for the reusable Dependency Review workflow.

Replaces argos's, mightyETL's, newsdom-api's, and scopeweave's
independently hand-written ``dependency-review.yml`` files with one reusable
``workflow_call`` workflow, ``.github/workflows/dependency-review.yml``, plus
a thin caller left in each product repository. See
``docs/doctoring/dependency-review-reusable-workflow-consolidation.md`` and
``docs/adr/0024-dependency-review-reusable-workflow-consolidation.md`` for
why.
"""

from __future__ import annotations

from pathlib import Path

_WORKFLOW = Path(".github/workflows/dependency-review.yml")

_CHECKOUT_PIN = "9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0"
_DEPENDENCY_REVIEW_PIN = "a1d282b36b6f3519aa1f3fc636f609c47dddb294"


def _workflow_text() -> str:
    """Read the reusable Dependency Review workflow as UTF-8 text."""
    return _WORKFLOW.read_text(encoding="utf-8")


def test_declares_workflow_call_with_four_inputs_and_recorded_defaults() -> None:
    """Every genuinely-varying field found while auditing the five originals is an input."""
    workflow = _workflow_text()
    assert "on:\n  workflow_call:\n    inputs:" in workflow
    for name in (
        "fail_on_severity:",
        "allow_ghsas:",
        "continue_on_error:",
        "comment_summary_in_pr:",
    ):
        assert name in workflow

    assert 'default: "moderate"' in workflow
    assert 'default: ""' in workflow
    assert "default: false" in workflow
    assert 'default: "on-failure"' in workflow


def test_step_order_is_harden_then_checkout_then_preflight_then_gated_steps() -> None:
    """Trusted setup precedes preflight, review, evidence binding, and upload."""
    workflow = _workflow_text()
    order = [
        "Harden the runner",
        "actions/checkout@",
        "Check dependency graph availability",
        "Dependency review",
        "Bind dependency-by-dependency security evidence",
        "Upload exact-head release dependency evidence",
    ]
    positions = [workflow.index(marker) for marker in order]
    assert positions == sorted(positions), "steps are out of order"


def test_dependency_review_only_runs_after_successful_evidence_preflight() -> None:
    """The review cannot run without a successful dependency evidence response."""
    workflow = _workflow_text()
    assert (
        "if: steps.dependency_graph.outputs.available == 'true'\n"
        "        continue-on-error: ${{ inputs.continue_on_error }}"
        in workflow
    )
    assert "release dependency evidence is unavailable, so the gate cannot pass" in workflow


def test_inputs_are_forwarded_to_the_dependency_review_action() -> None:
    """fail_on_severity, allow_ghsas, and comment_summary_in_pr must reach the action untouched."""
    workflow = _workflow_text()
    assert "fail-on-severity: ${{ inputs.fail_on_severity }}" in workflow
    assert "allow-ghsas: ${{ inputs.allow_ghsas }}" in workflow
    assert "comment-summary-in-pr: ${{ inputs.comment_summary_in_pr }}" in workflow


def test_forbidden_gnu_family_licenses_are_denied_by_the_blocking_action() -> None:
    """Direct and transitive dependency changes must reject GPL-family licenses."""
    workflow = _workflow_text()
    deny_line = next(line for line in workflow.splitlines() if "deny-licenses:" in line)
    for family in ("GPL-3.0-only", "LGPL-3.0-only", "AGPL-3.0-only"):
        assert family in deny_line


def test_exact_head_structured_evidence_is_mandatory_and_uploaded() -> None:
    """A passing review must publish dependency rows bound to exact base/head SHAs."""
    workflow = _workflow_text()
    assert "ref: ${{ github.workflow_sha }}" in workflow
    assert "scripts/ci/release_dependency_evidence.py" in workflow
    assert "--base-sha \"$BASE_SHA\"" in workflow
    assert "--head-sha \"$HEAD_SHA\"" in workflow
    assert "if-no-files-found: error" in workflow
    assert "Dependency-by-dependency evidence is missing or unsafe" in workflow


def test_harden_runner_audits_egress() -> None:
    """naruon's harden-runner step applies uniformly, not only to that one caller."""
    workflow = _workflow_text()
    assert "step-security/harden-runner@" in workflow
    assert "egress-policy: audit" in workflow


def test_action_pins_are_current_and_uniform() -> None:
    """checkout and dependency-review-action share one current pin, not per-caller drift."""
    workflow = _workflow_text()
    assert f"actions/checkout@{_CHECKOUT_PIN}" in workflow
    assert (
        f"actions/dependency-review-action@{_DEPENDENCY_REVIEW_PIN}" in workflow
    )


def test_uniform_fields_are_hardcoded_not_parameterized() -> None:
    """Fields byte-identical across all four originals stay static, not inputs."""
    workflow = _workflow_text()
    assert "permissions:\n  contents: read\n  pull-requests: read" in workflow
    assert "persist-credentials: false" in workflow


def test_forces_node24_runtime_for_js_actions() -> None:
    """newsdom-api's Node24 opt-in applies uniformly, not only to that one caller."""
    workflow = _workflow_text()
    assert "FORCE_JAVASCRIPT_ACTIONS_TO_NODE24: true" in workflow


def test_availability_check_uses_the_dependency_graph_compare_api() -> None:
    """The preflight must query the real capability, not infer from repository visibility."""
    workflow = _workflow_text()
    assert "dependency-graph/compare" in workflow
    assert "github.event.repository.private" not in workflow


def test_availability_check_distinguishes_unavailable_from_genuine_failure() -> None:
    """Unavailable and unexpected API responses both fail the release gate."""
    workflow = _workflow_text()
    assert 'if [ "$status" = "403" ] || [ "$status" = "404" ]' in workflow
    assert "::error::Dependency graph compare returned HTTP" in workflow
    assert "::error::Dependency graph availability check failed with HTTP" in workflow
    assert "exit 1" in workflow


def test_availability_check_only_runs_the_gate_for_pull_request_events() -> None:
    """A non-pull_request trigger (e.g. workflow_dispatch) must skip the gate, not error,
    since base/head SHAs only exist on a pull_request event."""
    workflow = _workflow_text()
    assert '"${{ github.event_name }}" != "pull_request"' in workflow


def test_dependency_review_comment_summary_defaults_to_on_failure() -> None:
    """scopeweave's PR-comment-on-failure UX applies uniformly by default, overridable per caller.

    naruon explicitly overrides it to "never" -- see
    test_declares_workflow_call_with_four_inputs_and_recorded_defaults for
    the default assertion and test_inputs_are_forwarded_to_the_dependency_review_action
    for the forwarding assertion; this test just pins the specific default
    value chosen (scopeweave's original, not naruon's or some other value).
    """
    workflow = _workflow_text()
    assert 'comment_summary_in_pr:\n' in workflow
    assert 'default: "on-failure"' in workflow
