"""Contracts for complete review-agent invocation payload binding."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from dataclasses import replace
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
ROUTER_PATH = ROOT / "scripts" / "ci" / "agent_mention_router.py"
NOEMA_WORKFLOW = ROOT / ".github" / "workflows" / "agent-mention-noema-dispatch.yml"
OPENCODE_WORKFLOW = ROOT / ".github" / "workflows" / "agent-mention-opencode-dispatch.yml"


def _load_router() -> ModuleType:
    """Load the router module from the pull-request source tree."""

    module_name = "agent_mention_complete_payload_binding"
    spec = importlib.util.spec_from_file_location(module_name, ROUTER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _event() -> dict:
    """Return one complete trusted issue-comment event."""

    return {
        "repository": {"full_name": "ContextualWisdomLab/example"},
        "issue": {
            "number": 17,
            "pull_request": {"url": "https://api.github.test/pr/17"},
        },
        "comment": {
            "id": 91,
            "body": "@cwl-noema-review @opencode-agent review",
            "author_association": "MEMBER",
            "user": {"login": "maintainer", "type": "User"},
        },
        "pull_request": {
            "state": "open",
            "head": {"sha": "a" * 40},
            "base": {"ref": "main", "sha": "b" * 40},
        },
    }


def _digest(claim: dict[str, object]) -> str:
    """Return the canonical SHA-256 digest used by wrapper workflows."""

    canonical = json.dumps(
        claim,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def test_event_and_payloads_bind_exact_base_identity() -> None:
    """The request and both wrapper payloads carry the immutable base SHA."""

    router = _load_router()
    request = router.parse_event(_event())
    assert request is not None
    assert request.pull_request_base_branch == "main"
    assert request.pull_request_base_sha == "b" * 40

    for payload in (
        router.noema_payload(request)["client_payload"],
        router.opencode_payload(request)["client_payload"],
    ):
        assert payload["base_branch"] == "main"
        assert payload["pr_base_sha"] == "b" * 40

    malformed = _event()
    malformed["pull_request"]["base"]["sha"] = "not-a-sha"
    with pytest.raises(ValueError, match="base SHA"):
        router.parse_event(malformed)


def test_invocation_claim_binds_all_security_relevant_fields() -> None:
    """Every mutable dispatch field participates in the canonical digest."""

    router = _load_router()
    request = router.parse_event(_event())
    assert request is not None

    noema_claim = router.agent_invocation_claim(request, "cwl-noema-review")
    assert noema_claim == {
        "actor": "maintainer",
        "agent": "cwl-noema-review",
        "base_branch": "main",
        "base_sha": "b" * 40,
        "comment_id": 91,
        "head_sha": "a" * 40,
        "pr_number": 17,
        "repository": "ContextualWisdomLab/example",
    }

    opencode_claim = router.agent_invocation_claim(request, "opencode-agent")
    assert opencode_claim == {
        "actor": "maintainer",
        "agent": "opencode-agent",
        "base_branch": "main",
        "base_sha": "b" * 40,
        "comment_id": 91,
        "enable_auto_merge": False,
        "head_sha": "a" * 40,
        "merge_mode": "disabled",
        "pr_number": 17,
        "repository": "ContextualWisdomLab/example",
        "review_dispatch_limit": "1",
        "trigger_reviews": True,
        "update_branches": False,
    }

    noema_key = router.agent_invocation_key(request, "cwl-noema-review")
    opencode_key = router.agent_invocation_key(request, "opencode-agent")
    assert noema_key == _digest(noema_claim)
    assert opencode_key == _digest(opencode_claim)

    changed_base = replace(request, pull_request_base_sha="c" * 40)
    assert router.agent_invocation_key(
        changed_base, "cwl-noema-review"
    ) != noema_key

    for field, replacement in (
        ("trigger_reviews", False),
        ("review_dispatch_limit", "2"),
        ("enable_auto_merge", True),
        ("update_branches", True),
        ("merge_mode", "direct_or_auto"),
    ):
        altered = dict(opencode_claim)
        altered[field] = replacement
        assert _digest(altered) != opencode_key


def test_wrappers_recompute_complete_claim_before_ledger_access() -> None:
    """Both wrappers fail closed before reusing an exact-name artifact claim."""

    noema = NOEMA_WORKFLOW.read_text(encoding="utf-8")
    opencode = OPENCODE_WORKFLOW.read_text(encoding="utf-8")
    for workflow in (noema, opencode):
        assert "PR_BASE_SHA:" in workflow
        assert "github.event.client_payload.pr_base_sha" in workflow
        assert '! [[ "$PR_BASE_SHA" =~ ^[0-9a-f]{40}$ ]]' in workflow
        assert '"base_sha": os.environ["PR_BASE_SHA"]' in workflow
        assert "hmac.compare_digest" in workflow
        assert workflow.index("Validate exact invocation payload") < workflow.index(
            "Inspect exact-name Actions artifact ledger"
        )
        assert "--arg pr_base_sha \"$PR_BASE_SHA\"" in workflow
        assert "pr_base_sha: $pr_base_sha" in workflow

    for field in (
        '"trigger_reviews": os.environ["TRIGGER_REVIEWS"] == "true"',
        '"review_dispatch_limit": os.environ["REVIEW_DISPATCH_LIMIT"]',
        '"enable_auto_merge": os.environ["ENABLE_AUTO_MERGE"] == "true"',
        '"update_branches": os.environ["UPDATE_BRANCHES"] == "true"',
        '"merge_mode": os.environ["MERGE_MODE"]',
    ):
        assert field in opencode

    assert noema.count('"base_sha": os.environ["PR_BASE_SHA"]') >= 2
    for field in (
        '"trigger_reviews": os.environ["TRIGGER_REVIEWS"] == "true"',
        '"review_dispatch_limit": os.environ["REVIEW_DISPATCH_LIMIT"]',
        '"enable_auto_merge": os.environ["ENABLE_AUTO_MERGE"] == "true"',
        '"update_branches": os.environ["UPDATE_BRANCHES"] == "true"',
        '"merge_mode": os.environ["MERGE_MODE"]',
    ):
        assert opencode.count(field) >= 2


def test_repository_dispatch_payloads_stay_within_github_property_limit() -> None:
    """Keep both OpenCode dispatch hops at GitHub's ten-property API boundary."""

    router = _load_router()
    request = router.parse_event(_event())
    assert request is not None
    noema_payload = router.noema_payload(request)["client_payload"]
    opencode_payload = router.opencode_payload(request)["client_payload"]

    assert len(noema_payload) <= 10
    assert set(opencode_payload) == {
        "target_repository",
        "pr_number",
        "pr_head_sha",
        "pr_base_sha",
        "base_branch",
        "requested_agent",
        "agent_invocation_key",
        "requested_by",
        "source_comment_id",
    }
    assert len(opencode_payload) <= 10

    workflow = OPENCODE_WORKFLOW.read_text(encoding="utf-8")
    for constant in (
        'TRIGGER_REVIEWS: "true"',
        'REVIEW_DISPATCH_LIMIT: "1"',
        'ENABLE_AUTO_MERGE: "false"',
        'UPDATE_BRANCHES: "false"',
        'MERGE_MODE: "disabled"',
    ):
        assert constant in workflow

    forward = workflow.split(
        "      - name: Forward once to the authoritative review-only scheduler\n", 1
    )[1]
    payload_literal = forward.split("client_payload: {\n", 1)[1].split(
        "\n              }\n            }'", 1
    )[0]
    forwarded_keys = {
        line.strip().split(":", 1)[0]
        for line in payload_literal.splitlines()
        if ":" in line
    }
    assert forwarded_keys == {
        "target_repository",
        "pr_number",
        "pr_head_sha",
        "pr_base_sha",
        "base_branch",
        "enable_auto_merge",
        "update_branches",
        "merge_mode",
        "agent_invocation_key",
        "source_comment_id",
    }
    assert len(forwarded_keys) <= 10
    assert "requested_agent:" not in payload_literal
    assert "requested_by:" not in payload_literal


def test_no_pr_specific_writer_workflow_remains() -> None:
    """Complete binding is implemented in canonical files, never a branch writer."""

    forbidden = sorted(
        str(path.relative_to(ROOT))
        for pattern in (
            "repair-pr787*.yml",
            "*pr787*final*.yml",
            "*agent-mention*repair*.yml",
        )
        for path in (ROOT / ".github" / "workflows").glob(pattern)
    )
    assert forbidden == []
