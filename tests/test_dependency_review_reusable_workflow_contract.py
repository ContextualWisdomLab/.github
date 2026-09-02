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


def test_declares_workflow_call_with_three_inputs_and_recorded_defaults() -> None:
    """Every genuinely-varying field found while auditing the four originals is an input."""
    workflow = _workflow_text()
    assert "on:\n  workflow_call:\n    inputs:" in workflow
    for name in ("fail_on_severity:", "allow_ghsas:", "continue_on_error:"):
        assert name in workflow

    assert 'default: "moderate"' in workflow
    assert 'default: ""' in workflow
    assert "default: false" in workflow


def test_step_order_is_checkout_then_preflight_then_dependency_review() -> None:
    """Checkout, capability preflight, then the gated action must remain ordered."""
    workflow = _workflow_text()
    order = [
        "actions/checkout@",
        "Check dependency graph availability",
        "Dependency review",
    ]
    positions = [workflow.index(marker) for marker in order]
    assert positions == sorted(positions), "steps are out of order"


def test_dependency_review_runs_only_after_a_confirmed_successful_comparison() -> None:
    """The action must execute only after the compare endpoint returned HTTP 200."""
    workflow = _workflow_text()
    assert (
        "if: steps.dependency_graph.outputs.available == 'true'\n"
        "        continue-on-error: ${{ inputs.continue_on_error }}"
        in workflow
    )
    assert 'if [ "$status" = "200" ]; then' in workflow
    assert 'echo "available=true" >>"$GITHUB_OUTPUT"' in workflow


def test_inputs_are_forwarded_to_the_dependency_review_action() -> None:
    """fail_on_severity and allow_ghsas must reach the underlying action untouched."""
    workflow = _workflow_text()
    assert "fail-on-severity: ${{ inputs.fail_on_severity }}" in workflow
    assert "allow-ghsas: ${{ inputs.allow_ghsas }}" in workflow


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


def test_pull_request_http_403_and_404_are_not_normalized_to_unavailable() -> None:
    """Authorization-shaped HTTP responses are ambiguous and must remain blocking.

    GitHub may use 403 or 404 for permission/policy failures as well as feature
    availability boundaries. A reusable security gate therefore cannot turn
    either response into success or delegate coverage to another scanner.
    """
    workflow = _workflow_text()
    assert 'if [ "$status" = "403" ] || [ "$status" = "404" ]' not in workflow
    assert "skipping the dependency-review hard gate" not in workflow
    assert "Dependency graph unavailable note" not in workflow
    assert "::error::Dependency graph comparison failed with HTTP" in workflow
    assert "exit 1" in workflow


def test_availability_check_only_runs_the_gate_for_pull_request_events() -> None:
    """A non-pull_request trigger may skip because it has no PR base/head identity."""
    workflow = _workflow_text()
    assert '"${{ github.event_name }}" != "pull_request"' in workflow


def test_dependency_review_posts_a_pr_comment_on_failure() -> None:
    """scopeweave's PR-comment-on-failure UX applies uniformly, not only to that one caller."""
    workflow = _workflow_text()
    assert "comment-summary-in-pr: on-failure" in workflow
