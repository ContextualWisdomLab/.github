"""Hostile-case runtime coverage for the explicit source-repair control plane."""
from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from scripts.ci import agent_source_repair as repair


REPOSITORY = "ContextualWisdomLab/bandscope"
BASE_SHA = "b" * 40
HEAD_SHA = "a" * 40
BODY = "@cwl-source-fix\nFix the bounded regression."
CREATED_AT = "2026-09-14T00:10:00Z"


def _policy(**overrides: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "version": 1,
        "enabled": True,
        "not_before": "2026-09-14T00:00:00Z",
    }
    value.update(overrides)
    return value


def _encoded_policy(value: Any | None = None) -> dict[str, Any]:
    payload = _policy() if value is None else value
    return {
        "type": "file",
        "encoding": "base64",
        "content": base64.b64encode(json.dumps(payload).encode()).decode(),
    }


def _pull(*, state: str = "open", changed_files: int = 2) -> dict[str, Any]:
    return {
        "state": state,
        "changed_files": changed_files,
        "base": {"ref": "develop", "sha": BASE_SHA},
        "head": {
            "ref": "fix/current-pr",
            "sha": HEAD_SHA,
            "repo": {"full_name": REPOSITORY},
        },
    }


def _comment(body: str = BODY, **overrides: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "id": 9001,
        "body": body,
        "author_association": "MEMBER",
        "created_at": CREATED_AT,
        "updated_at": CREATED_AT,
        "user": {"login": "maintainer", "type": "User"},
    }
    value.update(overrides)
    return value


def _expected(body: str = BODY) -> repair.ExpectedSourceRepair:
    return repair.expected_from_comment(REPOSITORY, 7, _pull(), _comment(body))


class FakeClient:
    """Serve exact GitHub API records while retaining every request for assertions."""

    def __init__(self) -> None:
        self.pull: Any = _pull()
        self.branch: Any = {"protected": False}
        self.permission: Any = {"permission": "write"}
        self.comment: Any = _comment()
        self.policy: Any = _encoded_policy()
        self.files: Any = [[
            {"filename": "src/player.rs", "status": "modified"},
            {"filename": "docs/notes.md", "status": "added"},
        ]]
        self.conversation: Any = [[]]
        self.raise_policy: Exception | None = None
        self.raise_ack: Exception | None = None
        self.calls: list[tuple[list[str], Any]] = []

    def request(self, args: list[str], *, input_payload: Any = None) -> Any:
        self.calls.append((list(args), input_payload))
        endpoint = args[0]
        if endpoint.endswith("/pulls/7"):
            return self.pull
        if "/branches/" in endpoint:
            return self.branch
        if "/collaborators/maintainer/permission" in endpoint:
            return self.permission
        if endpoint.endswith("/issues/comments/9001"):
            return self.comment
        if "/contents/.github/cwl-agent-source-repair.json" in endpoint:
            if self.raise_policy is not None:
                raise self.raise_policy
            return self.policy
        if endpoint.endswith("/pulls/7/files"):
            return self.files
        if endpoint.endswith("/issues/7/comments"):
            if "POST" in args:
                if self.raise_ack is not None:
                    raise self.raise_ack
                return {"id": 42}
            return self.conversation
        raise AssertionError(f"unexpected request: {args!r}")


class DispatchClient:
    """Capture central repository_dispatch requests."""

    def __init__(self) -> None:
        self.calls: list[tuple[list[str], Any]] = []

    def request(self, args: list[str], *, input_payload: Any = None) -> Any:
        self.calls.append((list(args), input_payload))
        return None


def test_flatten_pages_accepts_flat_and_nested_and_rejects_malformed() -> None:
    assert repair._flatten_pages([{"id": 1}]) == [{"id": 1}]
    assert repair._flatten_pages([[{"id": 1}], [{"id": 2}]]) == [{"id": 1}, {"id": 2}]
    with pytest.raises(repair.SourceRepairError, match="must be a list"):
        repair._flatten_pages({"id": 1})
    with pytest.raises(repair.SourceRepairError, match="invalid page"):
        repair._flatten_pages([[{"id": 1}], "bad"])


def test_timestamp_requires_valid_timezone_and_normalizes_to_utc() -> None:
    assert repair.parse_timestamp("2026-09-14T09:00:00+09:00").isoformat() == "2026-09-14T00:00:00+00:00"
    with pytest.raises(repair.SourceRepairError, match="missing or invalid"):
        repair.parse_timestamp("not-a-time")
    with pytest.raises(repair.SourceRepairError, match="timezone"):
        repair.parse_timestamp("2026-09-14T00:00:00")


def test_command_parser_rejects_review_handles_empty_and_oversized_instructions() -> None:
    assert repair.parse_source_command("") is None
    assert repair.parse_source_command("\n  \n") is None
    assert repair.parse_source_command("@opencode-agent fix\nDo it") is None
    assert repair.parse_source_command("text first\n@cwl-source-fix\nDo it") is None
    assert repair.parse_source_command("@cwl-source-fix: Fix it") == ("fix", "Fix it")
    assert repair.parse_source_command("\n@cwl-source-fix\nline one\nline two") == (
        "fix",
        "line one\nline two",
    )
    with pytest.raises(repair.SourceRepairError, match="no instruction"):
        repair.parse_source_command("@cwl-source-fix")
    with pytest.raises(repair.SourceRepairError, match="bounded limit"):
        repair.parse_source_command("@cwl-source-fix\n" + "x" * (repair.MAX_COMMAND_CHARS + 1))


@pytest.mark.parametrize(
    ("path", "safe"),
    [
        ("src/player.rs", True),
        (" src/player.rs", False),
        ("/absolute", False),
        ("src/../escape", False),
        ("src/bad\nname", False),
        ("src/`bad`", False),
        (".github/workflows/x.yml", False),
        ("scripts/ci/x.py", False),
        (".git/config", False),
        ("", False),
    ],
)
def test_safe_edit_path(path: str, safe: bool) -> None:
    assert repair._safe_edit_path(path) is safe


def test_expected_identity_validation_rejects_each_malformed_field() -> None:
    value = _expected()
    invalid = [
        (replace(value, repository="OtherOrg/repo"), "limited"),
        (replace(value, pull_request_number=0), "positive"),
        (replace(value, source_comment_id=0), "positive"),
        (replace(value, pull_request_base_ref="-bad"), "base ref"),
        (replace(value, pull_request_head_ref="-bad"), "head ref"),
        (replace(value, pull_request_base_sha="bad"), "base SHA"),
        (replace(value, pull_request_head_sha="bad"), "head SHA"),
        (replace(value, source_comment_sha256="bad"), "comment digest"),
        (replace(value, requested_by="bad user"), "actor"),
    ]
    for expected, message in invalid:
        with pytest.raises(repair.SourceRepairError, match=message):
            repair._validate_expected(expected)


def test_expected_from_comment_rejects_non_commands_bots_outsiders_closed_and_forks() -> None:
    with pytest.raises(repair.SourceRepairNotRequested):
        repair.expected_from_comment(REPOSITORY, 7, _pull(), _comment("hello"))
    with pytest.raises(repair.SourceRepairNotRequested, match="bot"):
        repair.expected_from_comment(
            REPOSITORY, 7, _pull(), _comment(user={"login": "bot", "type": "Bot"})
        )
    with pytest.raises(repair.SourceRepairError, match="trusted"):
        repair.expected_from_comment(
            REPOSITORY, 7, _pull(), _comment(author_association="NONE")
        )
    with pytest.raises(repair.SourceRepairNotRequested, match="open"):
        repair.expected_from_comment(REPOSITORY, 7, _pull(state="closed"), _comment())
    fork = _pull()
    fork["head"]["repo"]["full_name"] = "someone/fork"
    with pytest.raises(repair.SourceRepairError, match="same-repository"):
        repair.expected_from_comment(REPOSITORY, 7, fork, _comment())
    with pytest.raises(repair.SourceRepairError, match="identifier"):
        repair.expected_from_comment(REPOSITORY, 7, _pull(), _comment(id="not-int"))


def test_expected_from_dispatch_parses_valid_payload_and_rejects_shape_and_types() -> None:
    expected = _expected()
    payload = repair.dispatch_payload(
        repair.ValidatedSourceRepair(expected, "Fix it", "fix", CREATED_AT, ("src/player.rs",))
    )["client_payload"]
    assert repair.expected_from_dispatch({"client_payload": payload}) == expected
    with pytest.raises(repair.SourceRepairError, match="must be an object"):
        repair.expected_from_dispatch({"client_payload": []})
    malformed = dict(payload)
    malformed["pr_number"] = []
    with pytest.raises(repair.SourceRepairError, match="malformed"):
        repair.expected_from_dispatch({"client_payload": malformed})
    missing_number = dict(payload)
    del missing_number["pr_number"]
    with pytest.raises(repair.SourceRepairError, match="positive"):
        repair.expected_from_dispatch({"client_payload": missing_number})


def test_policy_is_exact_versioned_protected_base_contract() -> None:
    client = FakeClient()
    expected = _expected()
    assert repair._read_policy(client, expected).isoformat() == "2026-09-14T00:00:00+00:00"
    client.raise_policy = RuntimeError("HTTP 404")
    with pytest.raises(repair.SourceRepairNotEnabled, match="no protected-base"):
        repair._read_policy(client, expected)
    client.raise_policy = RuntimeError("HTTP 500")
    with pytest.raises(RuntimeError, match="500"):
        repair._read_policy(client, expected)


@pytest.mark.parametrize(
    ("policy", "error_type", "message"),
    [
        ([], repair.SourceRepairError, "JSON object"),
        ({"version": 1, "enabled": True, "not_before": CREATED_AT, "extra": True}, repair.SourceRepairError, "unsupported fields"),
        ({"version": 2, "enabled": True, "not_before": CREATED_AT}, repair.SourceRepairError, "version"),
        ({"version": 1, "enabled": False, "not_before": CREATED_AT}, repair.SourceRepairNotEnabled, "disabled"),
    ],
)
def test_policy_semantic_rejections(policy: Any, error_type: type[Exception], message: str) -> None:
    client = FakeClient()
    client.policy = _encoded_policy(policy)
    with pytest.raises(error_type, match=message):
        repair._read_policy(client, _expected())


def test_policy_rejects_non_file_encoding_and_malformed_content() -> None:
    client = FakeClient()
    expected = _expected()
    client.policy = {"type": "dir", "encoding": "base64", "content": "e30="}
    with pytest.raises(repair.SourceRepairError, match="regular file"):
        repair._read_policy(client, expected)
    client.policy = {"type": "file", "encoding": "utf-8", "content": "{}"}
    with pytest.raises(repair.SourceRepairError, match="encoding"):
        repair._read_policy(client, expected)
    client.policy = {"type": "file", "encoding": "base64", "content": base64.b64encode(b"{").decode()}
    with pytest.raises(repair.SourceRepairError, match="malformed"):
        repair._read_policy(client, expected)


def test_changed_paths_filters_control_plane_and_removed_files() -> None:
    client = FakeClient()
    client.pull = _pull(changed_files=4)
    client.files = [[
        {"filename": "src/player.rs", "status": "modified"},
        {"filename": ".github/workflows/ci.yml", "status": "modified"},
        {"filename": "docs/old.md", "status": "removed"},
        {"filename": "docs/new.md", "status": "added"},
    ]]
    assert repair._changed_paths(client, _expected(), client.pull) == (
        "docs/new.md",
        "src/player.rs",
    )


@pytest.mark.parametrize("count", [-1, "2"])
def test_changed_paths_rejects_invalid_count(count: Any) -> None:
    client = FakeClient()
    live = _pull()
    live["changed_files"] = count
    with pytest.raises(repair.SourceRepairError, match="invalid changed_files"):
        repair._changed_paths(client, _expected(), live)


def test_changed_paths_rejects_limit_incomplete_duplicates_and_empty_safe_scope() -> None:
    client = FakeClient()
    live = _pull(changed_files=repair.MAX_PR_FILES + 1)
    with pytest.raises(repair.SourceRepairError, match="exceeds"):
        repair._changed_paths(client, _expected(), live)
    live = _pull(changed_files=3)
    with pytest.raises(repair.SourceRepairError, match="incomplete"):
        repair._changed_paths(client, _expected(), live)
    live = _pull(changed_files=2)
    client.files = [[
        {"filename": "src/player.rs", "status": "modified"},
        {"filename": "src/player.rs", "status": "modified"},
    ]]
    with pytest.raises(repair.SourceRepairError, match="duplicate"):
        repair._changed_paths(client, _expected(), live)
    client.files = [[
        {"filename": ".github/a.yml", "status": "modified"},
        {"filename": "docs/old.md", "status": "removed"},
    ]]
    with pytest.raises(repair.SourceRepairError, match="no safe"):
        repair._changed_paths(client, _expected(), live)


def test_live_validation_returns_exact_command_and_scope() -> None:
    validated = repair.validate_live_source_repair(FakeClient(), _expected())
    assert validated.command == "Fix the bounded regression."
    assert validated.verb == "fix"
    assert validated.allowed_paths == ("docs/notes.md", "src/player.rs")


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (lambda c: setattr(c, "pull", []), "no longer open"),
        (lambda c: c.pull["head"].update({"sha": "c" * 40}), "identity moved"),
        (lambda c: setattr(c, "branch", {"protected": True}), "protected"),
        (lambda c: setattr(c, "permission", {"permission": "read"}), "write/admin"),
        (lambda c: setattr(c, "comment", []), "unavailable"),
        (lambda c: c.comment.update({"user": {"login": "maintainer", "type": "Bot"}}), "human-authored"),
        (lambda c: c.comment.update({"user": {"login": "other", "type": "User"}}), "author changed"),
        (lambda c: c.comment.update({"author_association": "NONE"}), "trusted association"),
        (lambda c: c.comment.update({"body": "@cwl-source-fix\nChanged"}), "body changed"),
        (lambda c: c.comment.update({"updated_at": "2026-09-14T00:11:00Z"}), "edited comments"),
    ],
)
def test_live_validation_rejects_stale_or_revoked_authority(mutator: Any, message: str) -> None:
    client = FakeClient()
    mutator(client)
    with pytest.raises(repair.SourceRepairError, match=message):
        repair.validate_live_source_repair(client, _expected())


def test_live_validation_rejects_comment_that_lost_explicit_command() -> None:
    """Digest can still match after the command syntax disappears from the live body."""

    body = "review note without an explicit source-repair command"
    expected = replace(_expected(), source_comment_sha256=repair.comment_sha256(body))
    client = FakeClient()
    client.comment = _comment(body)
    with pytest.raises(repair.SourceRepairError, match="no longer contains"):
        repair.validate_live_source_repair(client, expected)


def test_live_validation_rejects_command_before_activation() -> None:
    client = FakeClient()
    client.policy = _encoded_policy(_policy(not_before="2026-09-14T00:20:00Z"))
    with pytest.raises(repair.SourceRepairNotEnabled, match="predates"):
        repair.validate_live_source_repair(client, _expected())


def test_claim_receipt_requires_bot_and_exact_revision_marker() -> None:
    expected = _expected()
    client = FakeClient()
    marker = repair.receipt_marker(expected)
    client.conversation = [[
        {"body": marker, "user": {"type": "User"}},
        {"body": "other", "user": {"type": "Bot"}},
    ]]
    assert repair.source_repair_already_claimed(client, expected) is False
    client.conversation = [[{"body": marker, "user": {"type": "Bot"}}]]
    assert repair.source_repair_already_claimed(client, expected) is True


def test_dispatch_dry_run_duplicate_success_and_ack_failure(capsys: pytest.CaptureFixture[str]) -> None:
    expected = _expected()
    target = FakeClient()
    dispatch = DispatchClient()
    assert repair.dispatch_source_repair(
        target_client=target, dispatch_client=dispatch, expected=expected, dry_run=True
    ) is False
    assert "DRY-RUN" in capsys.readouterr().out
    target.conversation = [[{"body": repair.receipt_marker(expected), "user": {"type": "Bot"}}]]
    with pytest.raises(repair.SourceRepairAlreadyClaimed):
        repair.dispatch_source_repair(target_client=target, dispatch_client=dispatch, expected=expected)
    target.conversation = [[]]
    assert repair.dispatch_source_repair(target_client=target, dispatch_client=dispatch, expected=expected)
    assert dispatch.calls[-1][1]["event_type"] == "agent-source-repair"
    target.raise_ack = RuntimeError("token secret should not escape")
    assert repair.dispatch_source_repair(target_client=target, dispatch_client=dispatch, expected=expected)
    assert "acknowledgement failed" in capsys.readouterr().out


def test_worker_context_writes_deterministic_nul_scope_hash_and_quoted_instruction(tmp_path: Path) -> None:
    expected = _expected("@cwl-source-fix\nline one\n\nline three")
    validated = repair.ValidatedSourceRepair(
        expected,
        "line one\n\nline three",
        "fix",
        CREATED_AT,
        ("src/z.rs", "src/a.rs", "src/z.rs"),
    )
    context = tmp_path / "context.md"
    allowed = tmp_path / "paths.zlist"
    repair.write_worker_context(validated, context_output=context, allowed_paths_output=allowed)
    assert allowed.read_bytes() == b"src/a.rs\0src/z.rs\0"
    expected_hash = hashlib.sha256(allowed.read_bytes()).hexdigest()
    assert allowed.with_name("paths.zlist.sha256").read_text().strip() == expected_hash
    text = context.read_text()
    assert "> line one\n>\n> line three" in text
    assert "`src/a.rs`" in text and "`src/z.rs`" in text


def test_load_event_requires_object(tmp_path: Path) -> None:
    good = tmp_path / "good.json"
    good.write_text("{}", encoding="utf-8")
    assert repair.load_event(str(good)) == {}
    bad = tmp_path / "bad.json"
    bad.write_text("[]", encoding="utf-8")
    with pytest.raises(repair.SourceRepairError, match="must be an object"):
        repair.load_event(str(bad))


def test_main_requires_event_and_token_then_writes_worker_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = tmp_path / "context.md"
    allowed = tmp_path / "paths.zlist"
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_EVENT_PATH", raising=False)
    with pytest.raises(SystemExit):
        repair.main(["--context-output", str(context), "--allowed-paths-output", str(allowed)])

    expected = _expected()
    validated = repair.ValidatedSourceRepair(expected, "Fix it", "fix", CREATED_AT, ("src/player.rs",))
    event = tmp_path / "event.json"
    event.write_text(json.dumps(repair.dispatch_payload(validated)), encoding="utf-8")
    with pytest.raises(SystemExit):
        repair.main([
            "--event-path", str(event),
            "--context-output", str(context),
            "--allowed-paths-output", str(allowed),
        ])

    monkeypatch.setenv("GH_TOKEN", "token")
    monkeypatch.setattr(repair, "GitHubClient", lambda token: FakeClient())
    assert repair.main([
        "--event-path", str(event),
        "--context-output", str(context),
        "--allowed-paths-output", str(allowed),
    ]) == 0
    assert context.exists() and allowed.read_bytes() == b"docs/notes.md\0src/player.rs\0"
