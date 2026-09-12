"""Executable structural regressions for Noema live-target admission boundaries."""

from pathlib import Path
import re

WORKFLOW_PATH = Path(".github/workflows/noema-review.yml")


def _workflow_text() -> str:
    """Return the reviewed Noema workflow source."""
    return WORKFLOW_PATH.read_text(encoding="utf-8")


def _step_body(workflow_text: str, step_name: str) -> str:
    """Return one named workflow step without borrowing sibling evidence."""
    step_match = re.search(
        rf"^      - name: {re.escape(step_name)}\n(?P<body>.*?)(?=^      - name:|\Z)",
        workflow_text,
        re.MULTILINE | re.DOTALL,
    )
    assert step_match is not None, step_name
    return step_match.group("body")


def test_initial_live_admission_precedes_every_setup_step() -> None:
    """Closed or draft exact-head targets must skip credentials and trusted setup."""
    workflow_text = _workflow_text()
    admission_name = "Validate live Noema target before any setup"
    admission_index = workflow_text.index(f"      - name: {admission_name}\n")
    for later_step in (
        "Resolve trusted Noema review source ref",
        "Materialize trusted Noema review gate",
        "Cancel superseded Noema runs after live-head validation",
        "Select fail-closed Noema reviewer credential",
        "Mint repository-scoped Noema GitHub App token",
        "Exchange Noema app token through OIDC",
    ):
        later_index = workflow_text.index(f"      - name: {later_step}\n")
        assert admission_index < later_index, later_step
        assert "steps.live_pr.outputs.proceed == 'true'" in _step_body(workflow_text, later_step)

    admission_body = _step_body(workflow_text, admission_name)
    assert "        id: live_pr\n" in admission_body
    assert "GH_TOKEN: ${{ github.token }}" in admission_body
    assert "live_state=" in admission_body
    assert "live_head_sha=" in admission_body
    assert "live_draft=" in admission_body
    assert 'echo "proceed=false" >>"$GITHUB_OUTPUT"' in admission_body
    assert 'echo "proceed=true" >>"$GITHUB_OUTPUT"' in admission_body
    assert "EXPECTED_HEAD_SHA" in admission_body
    assert "live_head_sha,," in admission_body


def test_destructive_stale_run_cancellation_revalidates_state_head_and_draft() -> None:
    """A cancellation candidate must be rechecked against authoritative live PR state."""
    workflow_text = _workflow_text()
    cancellation_body = _step_body(
        workflow_text,
        "Cancel superseded Noema runs after live-head validation",
    )
    assert "live_pr_json=" in cancellation_body
    assert "live_head=" in cancellation_body
    assert "live_state=" in cancellation_body
    assert "live_draft=" in cancellation_body
    assert '[ "$live_state" != "open" ]' in cancellation_body
    assert '[ "$live_draft" = "true" ]' in cancellation_body
    assert "EXPECTED_HEAD_SHA" in cancellation_body
    assert cancellation_body.index("live_pr_json=") < cancellation_body.index("/cancel")


def test_model_and_publication_boundaries_refresh_live_state() -> None:
    """Model work and publication must each use a fresh state/head/draft decision."""
    workflow_text = _workflow_text()
    refresh_name = "Revalidate live Noema target before model setup"
    publish_name = "Revalidate live Noema target before publication"
    for step_name, step_id in (
        (refresh_name, "live_pr_refresh"),
        (publish_name, "live_pr_publish"),
    ):
        step_body = _step_body(workflow_text, step_name)
        assert f"        id: {step_id}\n" in step_body
        assert "GH_TOKEN: ${{ github.token }}" in step_body
        assert "live_state=" in step_body
        assert "live_head_sha=" in step_body
        assert "live_draft=" in step_body
        assert 'echo "proceed=false" >>"$GITHUB_OUTPUT"' in step_body
        assert 'echo "proceed=true" >>"$GITHUB_OUTPUT"' in step_body
        assert "EXPECTED_HEAD_SHA" in step_body
        assert "live_head_sha,," in step_body

    for model_step in (
        "Resolve Noema target repository visibility",
        "Provision contextual-orchestrator review sidecar",
        "Prepare Noema model verdict",
    ):
        assert "steps.live_pr_refresh.outputs.proceed == 'true'" in _step_body(
            workflow_text,
            model_step,
        )

    for publication_step in (
        "Refresh repository-scoped Noema GitHub App token for publication",
        "Publish prepared Noema verdict on the exact live head",
    ):
        assert "steps.live_pr_publish.outputs.proceed == 'true'" in _step_body(
            workflow_text,
            publication_step,
        )


def test_temporary_pr1674_self_modifying_lane_is_absent() -> None:
    """The reviewed head, not a post-review workflow successor, owns the repair."""
    assert not Path(".github/workflows/_temp_pr1674_strix_live_state_repair.yml").exists()
    assert not Path("scripts/ci/temp_pr1674_noema_closed_finalize.py").exists()
    assert not Path(".github/.pr1674-repair-trigger").exists()
