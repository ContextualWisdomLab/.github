"""Contract: mention repository_dispatch payloads stay within GitHub's 10-key limit."""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
ROUTER_PATH = ROOT / "scripts" / "ci" / "agent_mention_router.py"
NOEMA_WORKFLOW = ROOT / ".github" / "workflows" / "agent-mention-noema-dispatch.yml"
OPENCODE_WORKFLOW = ROOT / ".github" / "workflows" / "agent-mention-opencode-dispatch.yml"
GITHUB_DOCS = (
    "https://docs.github.com/en/rest/repos/repos#create-a-repository-dispatch-event"
)
WRAPPER_CLIENT_PAYLOAD_RE = re.compile(
    r"client_payload:\s*\{(?P<body>.*?)^\s+\}",
    re.MULTILINE | re.DOTALL,
)
WRAPPER_PAYLOAD_KEY_RE = re.compile(r"^\s+([A-Za-z_][A-Za-z0-9_]*):", re.MULTILINE)
REQUIRED_IDENTITY_KEYS = frozenset(
    {
        "target_repository",
        "pr_number",
        "pr_head_sha",
        "source_comment_id",
    }
)
OPENCODE_FORWARD_SAFETY_KEYS = frozenset(
    {
        "enable_auto_merge",
        "update_branches",
        "merge_mode",
    }
)


def _load_router() -> ModuleType:
    """Load the router module from the pull-request source tree."""

    module_name = "agent_mention_dispatch_payload_limit"
    spec = importlib.util.spec_from_file_location(module_name, ROUTER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _request(module: ModuleType):
    """Return one complete trusted mention request."""

    return module.MentionRequest(
        "ContextualWisdomLab/example",
        17,
        "a" * 40,
        "main",
        91,
        "maintainer",
        ("cwl-noema-review", "opencode-agent"),
        pull_request_base_sha="b" * 40,
    )


def _wrapper_forward_payload_keys(workflow_text: str) -> tuple[str, ...]:
    """Extract top-level client_payload keys from one wrapper forwarder."""

    match = WRAPPER_CLIENT_PAYLOAD_RE.search(workflow_text)
    assert match is not None
    keys = tuple(WRAPPER_PAYLOAD_KEY_RE.findall(match.group("body")))
    assert keys
    assert len(keys) == len(set(keys))
    return keys


def test_github_repository_dispatch_limit_is_ten_top_level_keys() -> None:
    """The router constant matches GitHub's documented client_payload cap."""

    router = _load_router()
    assert router.REPOSITORY_DISPATCH_CLIENT_PAYLOAD_MAX_KEYS == 10
    assert GITHUB_DOCS in (
        ROOT / "docs" / "automation" / "review-agent-comment-invocation.md"
    ).read_text(encoding="utf-8")


def test_mention_router_payloads_stay_within_github_key_limit() -> None:
    """Both first-hop mention dispatches keep identity without exceeding 10 keys."""

    router = _load_router()
    request = _request(router)
    noema = router.noema_payload(request)["client_payload"]
    opencode = router.opencode_payload(request)["client_payload"]
    limit = router.REPOSITORY_DISPATCH_CLIENT_PAYLOAD_MAX_KEYS

    assert len(noema) <= limit
    assert len(opencode) <= limit
    assert REQUIRED_IDENTITY_KEYS <= noema.keys()
    assert REQUIRED_IDENTITY_KEYS <= opencode.keys()
    assert {
        "trigger_reviews",
        "review_dispatch_limit",
        "enable_auto_merge",
        "update_branches",
        "merge_mode",
    }.isdisjoint(opencode.keys())


def test_wrapper_forwarders_stay_within_github_key_limit() -> None:
    """Mention-forwarder jq payloads also stay at or under 10 top-level keys."""

    router = _load_router()
    limit = router.REPOSITORY_DISPATCH_CLIENT_PAYLOAD_MAX_KEYS
    noema_keys = _wrapper_forward_payload_keys(
        NOEMA_WORKFLOW.read_text(encoding="utf-8")
    )
    opencode_keys = _wrapper_forward_payload_keys(
        OPENCODE_WORKFLOW.read_text(encoding="utf-8")
    )

    assert len(noema_keys) <= limit
    assert len(opencode_keys) <= limit
    assert REQUIRED_IDENTITY_KEYS <= set(noema_keys)
    assert REQUIRED_IDENTITY_KEYS <= set(opencode_keys)
    assert OPENCODE_FORWARD_SAFETY_KEYS <= set(opencode_keys)
    assert "trigger_reviews" not in opencode_keys
    assert "review_dispatch_limit" not in opencode_keys
    assert "requested_agent" not in opencode_keys
    assert "requested_by" not in opencode_keys


def test_repository_dispatch_body_rejects_more_than_ten_keys() -> None:
    """An oversized client_payload fails closed before GitHub returns HTTP 422."""

    router = _load_router()
    oversized = {f"field_{index}": index for index in range(11)}
    with pytest.raises(ValueError, match="GitHub allows at most 10"):
        router.repository_dispatch_body("agent-mention-opencode", oversized)
