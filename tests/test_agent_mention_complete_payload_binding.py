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

    noema_payload = router.noema_payload(request)["client_payload"]
    assert noema_payload["base_branch"] == "main"
    assert noema_payload["pr_base_sha"] == "b" * 40
    opencode_envelope = router.opencode_payload(request)["client_payload"]
    assert opencode_envelope["schema"] == "cwl.agent-invocation/v2"
    assert opencode_envelope["claim"]["base_branch"] == "main"
    assert opencode_envelope["claim"]["base_sha"] == "b" * 40

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
    assert "PR_BASE_SHA:" in noema
    assert "github.event.client_payload.pr_base_sha" in noema
    assert '! [[ "$PR_BASE_SHA" =~ ^[0-9a-f]{40}$ ]]' in noema
    assert '"base_sha": os.environ["PR_BASE_SHA"]' in noema
    assert "--arg pr_base_sha \"$PR_BASE_SHA\"" in noema
    assert "pr_base_sha: $pr_base_sha" in noema
    assert noema.count('"base_sha": os.environ["PR_BASE_SHA"]') >= 2

    assert "CLIENT_PAYLOAD_JSON:" in opencode
    assert "github.event.client_payload.claim" in opencode
    assert '"base_sha"' in opencode
    assert 'r"[0-9a-f]{40}", claim["base_sha"]' in opencode
    assert "set(envelope)" in opencode
    assert "set(claim)" in opencode
    assert '"client_payload": envelope' in opencode
    assert '--input "$SCHEDULER_REQUEST_FILE"' in opencode
    for workflow in (noema, opencode):
        assert "hmac.compare_digest" in workflow
        assert workflow.index("Validate exact invocation payload") < workflow.index(
            "Inspect exact-name Actions artifact ledger"
        )

    for field, value in (
        ('"agent"', '"opencode-agent"'),
        ('"trigger_reviews"', "True"),
        ('"review_dispatch_limit"', '"1"'),
        ('"enable_auto_merge"', "False"),
        ('"update_branches"', "False"),
        ('"merge_mode"', '"disabled"'),
    ):
        assert f"{field}: {value}" in opencode


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
