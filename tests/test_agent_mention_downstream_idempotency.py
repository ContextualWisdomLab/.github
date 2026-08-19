"""Static contracts for downstream review-agent invocation idempotency."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROUTER_WORKFLOW = ROOT / ".github" / "workflows" / "agent-mention-router.yml"
QUALITY_WORKFLOW = ROOT / ".github" / "workflows" / "agent-mention-router-quality-ci.yml"
NOEMA_WORKFLOW = ROOT / ".github" / "workflows" / "agent-mention-noema-dispatch.yml"
OPENCODE_WORKFLOW = ROOT / ".github" / "workflows" / "agent-mention-opencode-dispatch.yml"
ROUTER_SCRIPT = ROOT / "scripts" / "ci" / "agent_mention_router.py"
UPLOAD_ARTIFACT_SHA = "043fb46d1a93c77aae656e7c1c64a875d1fc6a0a"


def test_router_can_read_durable_central_artifacts() -> None:
    """Both local routing and sibling sweeping receive actions read access."""

    text = ROUTER_WORKFLOW.read_text(encoding="utf-8")
    local, sweep = text.split("\n  sweep-organization-agent-mentions:\n", 1)
    assert "permissions:\n      actions: read" in local
    assert "permissions:\n      actions: read" in sweep
    assert "AGENT_DISPATCH_TOKEN: ${{ github.token }}" in local
    assert "AGENT_DISPATCH_TOKEN: ${{ github.token }}" in sweep


def test_downstream_workflows_claim_artifacts_and_bind_exact_key() -> None:
    """Exact-key concurrency serializes claims before authoritative forwarding."""

    noema = NOEMA_WORKFLOW.read_text(encoding="utf-8")
    opencode = OPENCODE_WORKFLOW.read_text(encoding="utf-8")
    for text in (noema, opencode):
        assert "github.event.client_payload.agent_invocation_key" in text
        assert "cwl-agent-invocation:" in text
        assert "source_comment_id" in text
        assert "requested_agent" in text
        assert "cancel-in-progress: false" in text
        assert "queue: max" in text
        assert "cancel-in-progress: true" not in text
        assert "^[0-9a-f]{64}$" in text
        assert "^[1-9][0-9]*$" in text
        assert "actions/artifacts" in text
        assert "name=${LEDGER_ARTIFACT_NAME}" in text
        assert f"actions/upload-artifact@{UPLOAD_ARTIFACT_SHA}" in text
        assert "retention-days: 30" in text
        assert "overwrite: false" in text
        assert text.index("actions/upload-artifact@") < text.index(
            "Forward once to the authoritative"
        )
        assert "workflow_runs" not in text
        assert "repos/${GITHUB_REPOSITORY}/dispatches" in text
    assert "queue: max" not in noema
    assert "queue: max" not in opencode
    assert "types: [agent-mention-noema]" in noema
    assert 'event_type: "noema-review"' in noema
    assert 'REQUESTED_AGENT: "cwl-noema-review"' in noema
    assert "types: [agent-mention-opencode]" in opencode
    assert 'event_type: "merge-scheduler"' in opencode
    assert 'REQUESTED_AGENT: "opencode-agent"' in opencode
    assert '[[ "$BASE_BRANCH" =~ ^[A-Za-z0-9._/-]+$ ]]' in opencode
    assert '[[ "$BASE_BRANCH" == -* ]]' in opencode


def test_wrappers_recompute_the_router_canonical_payload_digest() -> None:
    """A syntactically valid key cannot authorize altered payload fields."""

    router = ROUTER_SCRIPT.read_text(encoding="utf-8")
    noema_function = router.split("def noema_payload", 1)[1].split(
        "def opencode_payload", 1
    )[0]
    assert '"base_branch": request.pull_request_base_branch' in noema_function

    canonical_fields = (
        '"actor"',
        '"agent"',
        '"base_branch"',
        '"comment_id"',
        '"head_sha"',
        '"pr_number"',
        '"repository"',
    )
    for text in (
        NOEMA_WORKFLOW.read_text(encoding="utf-8"),
        OPENCODE_WORKFLOW.read_text(encoding="utf-8"),
    ):
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


def test_quality_gate_runs_full_suite_for_docs_and_exact_diff() -> None:
    """Every changed contract executes while coverage stays source-bounded."""

    text = QUALITY_WORKFLOW.read_text(encoding="utf-8")
    assert '      - "docs/automation/review-agent-comment-invocation.md"' in text
    assert '      - "tests/test_agent_mention_*.py"' in text
    assert "python -m coverage run -m pytest -q\n" in text
    assert "python -m compileall -q scripts/ci tests" in text
    assert "CHANGE_DIFF_RANGE" in text
    assert 'git diff --check "$CHANGE_DIFF_RANGE"' in text
    coverage_config = text.split("[run]\n", 1)[1].split("[report]\n", 1)[0]
    assert "scripts/ci/agent_mention_router.py" in coverage_config
    assert "scripts/ci/agent_mention_sweep.py" in coverage_config
