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
ROUTER_SCRIPT = ROOT / "scripts" / "ci" / "agent_mention_router.py"


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
    assert "^(?!-)" not in opencode
    assert '[[ "$BASE_BRANCH" =~ ^[A-Za-z0-9._/-]+$ ]]' in opencode
    assert '[[ "$BASE_BRANCH" == -* ]]' in opencode


def test_wrappers_recompute_the_router_canonical_payload_digest() -> None:
    """A syntactically valid key cannot authorize altered payload fields."""

    router = ROUTER_SCRIPT.read_text(encoding="utf-8")
    noema_function = router.split("def noema_payload", 1)[1].split(
        "def opencode_payload", 1
    )[0]
    assert '"base_branch": request.pull_request_base_branch' in noema_function

    noema = NOEMA_WORKFLOW.read_text(encoding="utf-8")
    opencode = OPENCODE_WORKFLOW.read_text(encoding="utf-8")
    canonical_fields = (
        '"actor"',
        '"agent"',
        '"base_branch"',
        '"comment_id"',
        '"head_sha"',
        '"pr_number"',
        '"repository"',
    )
    for text in (noema, opencode):
        assert "BASE_BRANCH:" in text
        assert "import hashlib" in text
        assert "import hmac" in text
        assert "json.dumps(" in text
        assert 'separators=(",", ":")' in text
        assert "sort_keys=True" in text
        assert "hashlib.sha256" in text
        assert "hmac.compare_digest" in text
        assert "INVOCATION_KEY" in text
        for field in canonical_fields:
            assert field in text


def test_quality_gate_tracks_every_idempotency_surface() -> None:
    """The permanent focused gate reruns and executes all bounded contracts."""

    text = QUALITY_WORKFLOW.read_text(encoding="utf-8")
    for workflow_path in (
        ".github/workflows/agent-mention-noema-dispatch.yml",
        ".github/workflows/agent-mention-opencode-dispatch.yml",
    ):
        assert f'      - "{workflow_path}"' in text

    assert '      - "tests/test_agent_mention_*.py"' in text
    test_command = text.split("python -m coverage run -m pytest -q", 1)[1]
    compile_command = text.split("python -m compileall -q", 1)[1]
    for test_path in (
        "tests/test_agent_mention_idempotency.py",
        "tests/test_agent_mention_downstream_idempotency.py",
    ):
        assert test_path in test_command
        assert test_path in compile_command
