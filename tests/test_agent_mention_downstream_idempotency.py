"""Static contracts for downstream review-agent invocation idempotency."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROUTER_WORKFLOW = ROOT / ".github" / "workflows" / "agent-mention-router.yml"
QUALITY_WORKFLOW = (
    ROOT / ".github" / "workflows" / "agent-mention-router-quality-ci.yml"
)
NOEMA_WORKFLOW = (
    ROOT / ".github" / "workflows" / "agent-mention-noema-dispatch.yml"
)
OPENCODE_WORKFLOW = (
    ROOT / ".github" / "workflows" / "agent-mention-opencode-dispatch.yml"
)


def test_router_can_read_durable_central_workflow_runs() -> None:
    """Both local routing and sibling sweeping receive actions read access."""

    text = ROUTER_WORKFLOW.read_text(encoding="utf-8")
    local, sweep = text.split("\n  sweep-organization-agent-mentions:\n", 1)
    assert "permissions:\n      actions: read" in local
    assert "permissions:\n      actions: read" in sweep
    assert "AGENT_DISPATCH_TOKEN: ${{ github.token }}" in local
    assert "AGENT_DISPATCH_TOKEN: ${{ github.token }}" in sweep


def test_downstream_workflows_bind_run_name_and_concurrency_to_exact_key() -> None:
    """Agent wrappers serialize and validate one exact invocation key."""

    noema = NOEMA_WORKFLOW.read_text(encoding="utf-8")
    opencode = OPENCODE_WORKFLOW.read_text(encoding="utf-8")
    for text in (noema, opencode):
        assert "github.event.client_payload.agent_invocation_key" in text
        assert "cwl-agent-invocation:" in text
        assert "source_comment_id" in text
        assert "requested_agent" in text
        assert "cancel-in-progress: false" in text
        assert "^[0-9a-f]{64}$" in text
        assert "^[1-9][0-9]*$" in text
        assert "repos/${GITHUB_REPOSITORY}/dispatches" in text
    assert "types: [agent-mention-noema]" in noema
    assert 'event_type: "noema-review"' in noema
    assert 'REQUESTED_AGENT: "cwl-noema-review"' in noema
    assert "types: [agent-mention-opencode]" in opencode
    assert 'event_type: "merge-scheduler"' in opencode
    assert 'REQUESTED_AGENT: "opencode-agent"' in opencode


def test_quality_gate_tracks_every_idempotency_surface() -> None:
    """The permanent focused gate reruns and executes all bounded contracts."""

    text = QUALITY_WORKFLOW.read_text(encoding="utf-8")
    for workflow_path in (
        '.github/workflows/agent-mention-noema-dispatch.yml',
        '.github/workflows/agent-mention-opencode-dispatch.yml',
    ):
        assert f'      - "{workflow_path}"' in text

    test_command = text.split("python -m coverage run -m pytest -q", 1)[1]
    for test_path in (
        'tests/test_agent_mention_idempotency.py',
        'tests/test_agent_mention_downstream_idempotency.py',
    ):
        assert f'      - "{test_path}"' in text
        assert test_path in test_command
