"""Contracts for explicit source-repair command admission and mutation authority."""
from __future__ import annotations

import base64
import json
from dataclasses import replace

import pytest

from scripts.ci.agent_source_repair import (
    SourceRepairError,
    comment_sha256,
    dispatch_payload,
    expected_from_comment,
    parse_source_command,
    receipt_marker,
    validate_live_source_repair,
)


class FakeClient:
    """Return deterministic GitHub API fixtures keyed by endpoint prefix."""

    def __init__(
        self,
        *,
        protected: bool = False,
        permission: str = "write",
        changed_files: int = 2,
        comment_body: str = "@opencode-agent fix\nFix the regression without widening scope.",
    ) -> None:
        self.protected = protected
        self.permission = permission
        self.changed_files = changed_files
        self.comment_body = comment_body
        self.created_at = "2026-09-14T00:10:00Z"

    def request(self, args, *, input_payload=None):
        """Serve the subset of GitHub calls used by source-repair validation."""
        endpoint = args[0]
        if endpoint.endswith("/pulls/7"):
            return {
                "state": "open",
                "changed_files": self.changed_files,
                "base": {"ref": "develop", "sha": "b" * 40},
                "head": {
                    "ref": "fix/regression",
                    "sha": "a" * 40,
                    "repo": {"full_name": "ContextualWisdomLab/bandscope"},
                },
            }
        if "/branches/" in endpoint:
            return {"protected": self.protected}
        if "/collaborators/maintainer/permission" in endpoint:
            return {"permission": self.permission}
        if endpoint.endswith("/issues/comments/9001"):
            return {
                "id": 9001,
                "body": self.comment_body,
                "author_association": "MEMBER",
                "created_at": self.created_at,
                "updated_at": self.created_at,
                "user": {"login": "maintainer", "type": "User"},
            }
        if "/contents/.github/cwl-agent-source-repair.json" in endpoint:
            policy = {
                "version": 1,
                "enabled": True,
                "not_before": "2026-09-14T00:00:00Z",
            }
            return {
                "type": "file",
                "encoding": "base64",
                "content": base64.b64encode(json.dumps(policy).encode()).decode(),
            }
        if endpoint.endswith("/pulls/7/files"):
            return [[
                {"filename": "src/player.rs", "status": "modified"},
                {"filename": ".github/workflows/unsafe.yml", "status": "modified"},
            ]]
        raise AssertionError(f"unexpected request: {args!r} payload={input_payload!r}")


def event(body: str) -> tuple[dict, dict]:
    """Build one same-repository live PR and human comment fixture."""
    pull = {
        "state": "open",
        "base": {"ref": "develop", "sha": "b" * 40},
        "head": {
            "ref": "fix/regression",
            "sha": "a" * 40,
            "repo": {"full_name": "ContextualWisdomLab/bandscope"},
        },
    }
    comment = {
        "id": 9001,
        "body": body,
        "author_association": "MEMBER",
        "created_at": "2026-09-14T00:10:00Z",
        "updated_at": "2026-09-14T00:10:00Z",
        "user": {"login": "maintainer", "type": "User"},
    }
    return pull, comment


@pytest.mark.parametrize("verb", ["fix", "repair", "FIX", "Repair"])
def test_explicit_source_command_is_first_line_and_bounded(verb: str) -> None:
    """Only an explicit first non-empty OpenCode fix/repair command authorizes mutation."""
    parsed = parse_source_command(f"\n@opencode-agent {verb}\nFix regression.")
    assert parsed == (verb.lower(), "Fix regression.")
    assert parse_source_command(f"Please @opencode-agent {verb} this") is None
    assert parse_source_command("@opencode-agent review\nFix regression.") is None


def test_validated_command_gets_safe_complete_pr_scope() -> None:
    """The worker may edit safe current-PR files but not control-plane paths."""
    body = "@opencode-agent fix\nFix the regression without widening scope."
    pull, comment = event(body)
    expected = expected_from_comment("ContextualWisdomLab/bandscope", 7, pull, comment)
    validated = validate_live_source_repair(FakeClient(comment_body=body), expected)
    assert validated.allowed_paths == ("src/player.rs",)
    payload = dispatch_payload(validated)
    assert payload["event_type"] == "agent-source-repair"
    assert len(payload["client_payload"]) <= 10
    assert payload["client_payload"]["source_comment_sha256"] == comment_sha256(body)
    assert receipt_marker(expected).endswith(f":{expected.source_comment_sha256} -->")


def test_protected_head_is_never_mutated() -> None:
    """Explicit repair refuses protected PR head branches even for repository writers."""
    body = "@opencode-agent repair\nFix it."
    pull, comment = event(body)
    expected = expected_from_comment("ContextualWisdomLab/bandscope", 7, pull, comment)
    with pytest.raises(SourceRepairError, match="protected"):
        validate_live_source_repair(FakeClient(protected=True, comment_body=body), expected)


def test_live_write_permission_is_required() -> None:
    """Stale author association cannot substitute for live write/admin permission."""
    body = "@opencode-agent fix\nFix it."
    pull, comment = event(body)
    expected = expected_from_comment("ContextualWisdomLab/bandscope", 7, pull, comment)
    with pytest.raises(SourceRepairError, match="write/admin"):
        validate_live_source_repair(FakeClient(permission="read", comment_body=body), expected)


def test_incomplete_files_receipt_fails_closed() -> None:
    """Changed-file scope cannot be inferred from a truncated PR Files receipt."""
    body = "@opencode-agent fix\nFix the regression without widening scope."
    pull, comment = event(body)
    expected = expected_from_comment("ContextualWisdomLab/bandscope", 7, pull, comment)
    with pytest.raises(SourceRepairError, match="incomplete"):
        validate_live_source_repair(FakeClient(changed_files=3, comment_body=body), expected)


def test_comment_revision_is_exactly_bound() -> None:
    """An edited command cannot inherit the dispatch authority of an earlier body."""
    body = "@opencode-agent fix\nFix it."
    pull, comment = event(body)
    expected = expected_from_comment("ContextualWisdomLab/bandscope", 7, pull, comment)
    with pytest.raises(SourceRepairError, match="body changed"):
        validate_live_source_repair(
            FakeClient(comment_body=body),
            replace(expected, source_comment_sha256="0" * 64),
        )
