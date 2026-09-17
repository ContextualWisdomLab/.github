from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "scripts" / "ci"))

import agent_source_fix_router as router  # noqa: E402
import agent_source_fix_worker as worker  # noqa: E402


HEAD = "a" * 40
BASE = "b" * 40


def _event(body: str = "@cwl-source-fix fix the authenticated PR scope") -> dict:
    return {
        "repository": {"full_name": "ContextualWisdomLab/.github"},
        "issue": {"number": 42, "pull_request": {"url": "https://example.invalid/pr/42"}},
        "comment": {
            "id": 7001,
            "body": body,
            "author_association": "OWNER",
            "user": {"login": "seonghobae", "type": "User"},
        },
        "pull_request": {
            "state": "open",
            "head": {"sha": HEAD, "ref": "fix/current-pr"},
            "base": {"sha": BASE, "ref": "main"},
        },
    }


def test_command_has_exact_boundaries() -> None:
    assert router.has_source_fix_command("please @cwl-source-fix repair this")
    assert not router.has_source_fix_command("https://example.com/@cwl-source-fix")
    assert not router.has_source_fix_command("prefix@cwl-source-fix")
    assert not router.has_source_fix_command("@cwl-source-fix/unsafe")


def test_parse_event_binds_exact_pr_and_instruction() -> None:
    event = _event()
    request = router.parse_event(event)
    assert request is not None
    assert request.repository == "ContextualWisdomLab/.github"
    assert request.pull_request_number == 42
    assert request.pull_request_head_sha == HEAD
    assert request.pull_request_base_sha == BASE
    assert request.instruction_sha256 == hashlib.sha256(
        event["comment"]["body"].encode("utf-8")
    ).hexdigest()


def test_untrusted_or_bot_comment_is_ignored() -> None:
    outsider = _event()
    outsider["comment"]["author_association"] = "NONE"
    assert router.parse_event(outsider) is None
    bot = _event()
    bot["comment"]["user"]["type"] = "Bot"
    assert router.parse_event(bot) is None


def test_dispatch_payload_is_exactly_github_limit_and_write_bounded() -> None:
    request = router.parse_event(_event())
    assert request is not None
    assert router.invocation_claim(request)["write_mode"] == "existing-pr-files-only"
    payload = router.dispatch_payload(request)
    assert payload["event_type"] == "agent-source-fix"
    assert len(payload["client_payload"]) == 10
    assert payload["client_payload"]["invocation_key"] == router.invocation_key(request)


def test_worker_accepts_same_canonical_claim(monkeypatch: pytest.MonkeyPatch) -> None:
    request = router.parse_event(_event())
    assert request is not None
    env = {
        "TARGET_REPOSITORY": request.repository,
        "PR_NUMBER": str(request.pull_request_number),
        "PR_HEAD_SHA": request.pull_request_head_sha,
        "PR_HEAD_REF": request.pull_request_head_ref,
        "PR_BASE_SHA": request.pull_request_base_sha,
        "PR_BASE_REF": request.pull_request_base_ref,
        "REQUESTED_BY": request.actor,
        "SOURCE_COMMENT_ID": str(request.comment_id),
        "INSTRUCTION_SHA256": request.instruction_sha256,
        "INVOCATION_KEY": router.invocation_key(request),
    }
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    assert worker.validate_static_inputs() == router.invocation_claim(request)


def test_worker_rejects_tampered_invocation(monkeypatch: pytest.MonkeyPatch) -> None:
    request = router.parse_event(_event())
    assert request is not None
    monkeypatch.setenv("TARGET_REPOSITORY", request.repository)
    monkeypatch.setenv("PR_NUMBER", str(request.pull_request_number))
    monkeypatch.setenv("PR_HEAD_SHA", request.pull_request_head_sha)
    monkeypatch.setenv("PR_HEAD_REF", request.pull_request_head_ref)
    monkeypatch.setenv("PR_BASE_SHA", request.pull_request_base_sha)
    monkeypatch.setenv("PR_BASE_REF", request.pull_request_base_ref)
    monkeypatch.setenv("REQUESTED_BY", request.actor)
    monkeypatch.setenv("SOURCE_COMMENT_ID", str(request.comment_id))
    monkeypatch.setenv("INSTRUCTION_SHA256", request.instruction_sha256)
    monkeypatch.setenv("INVOCATION_KEY", "0" * 64)
    with pytest.raises(ValueError, match="canonical source-fix claim"):
        worker.validate_static_inputs()


def test_worker_path_scope_rejects_traversal() -> None:
    assert worker._safe_path("scripts/ci/fix.py")
    assert not worker._safe_path("../escape.py")
    assert not worker._safe_path("/absolute/path")
    assert not worker._safe_path("bad\npath.py")


def test_worker_pr_file_scope_excludes_control_plane(monkeypatch: pytest.MonkeyPatch) -> None:
    records = [
        {"filename": "src/fix.py", "status": "modified"},
        {"filename": ".github/workflows/agent-source-fix-dispatch.yml", "status": "modified"},
        {"filename": "scripts/ci/agent_source_fix_worker.py", "status": "modified"},
        {"filename": ".git/config", "status": "modified"},
    ]
    monkeypatch.setattr(worker, "gh_json", lambda _args: records)

    assert worker._pr_files("ContextualWisdomLab/.github", 42, len(records)) == ("src/fix.py",)
