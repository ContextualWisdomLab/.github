"""Tests for trusted PR comment agent mention routing."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "ci" / "agent_mention_router.py"


def load_module() -> ModuleType:
    """Load the router module from its script path."""

    module_name = "agent_mention_router"
    spec = importlib.util.spec_from_file_location(module_name, MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def receipt(comment_id: int, *, trusted: bool = True) -> dict:
    """Build one trusted or attacker-controlled receipt-looking comment."""

    return {
        "body": f"<!-- cwl-agent-mention-receipt:{comment_id} -->",
        "user": {
            "login": "github-actions[bot]" if trusted else "attacker",
            "type": "Bot" if trusted else "User",
        },
    }


def event(
    body: str,
    *,
    association: str = "MEMBER",
    user_type: str = "User",
) -> dict:
    """Build a representative enriched issue-comment event."""

    return {
        "repository": {"full_name": "ContextualWisdomLab/example"},
        "issue": {
            "number": 17,
            "pull_request": {"url": "https://api.github.test/pr/17"},
        },
        "comment": {
            "id": 91,
            "body": body,
            "author_association": association,
            "user": {"login": "maintainer", "type": user_type},
        },
        "pull_request": {
            "state": "open",
            "head": {"sha": "a" * 40},
            "base": {"ref": "develop", "sha": "b" * 40},
        },
    }


class FakeClient:
    """Capture JSON API calls for deterministic dispatch assertions."""

    def __init__(self) -> None:
        """Initialize an empty call ledger."""

        self.calls: list[tuple[list[str], dict | None]] = []

    def request(self, args, *, input_payload=None):
        """Record one request and return an empty artifact inventory for reads."""

        self.calls.append((list(args), input_payload))
        if args[0].endswith("/actions/artifacts"):
            return {"total_count": 0, "artifacts": []}
        return None


def repository_dispatch_calls(
    client: FakeClient,
) -> list[tuple[list[str], dict]]:
    """Return only mutation calls that enqueue central repository dispatches."""

    return [
        (args, payload)
        for args, payload in client.calls
        if args[0].endswith("/dispatches") and payload is not None
    ]


def test_exact_mentions_and_parse_event() -> None:
    """Both exact mentions are recognized with immutable PR metadata."""

    module = load_module()
    request = module.parse_event(
        event("please @cwl-noema-review and @opencode-agent")
    )
    assert request is not None
    assert request.agents == ("cwl-noema-review", "opencode-agent")
    assert request.pull_request_head_sha == "a" * 40
    assert request.pull_request_base_branch == "develop"
    assert request.pull_request_base_sha == "b" * 40
    assert module.exact_mentions("@opencode-agent-evil @cwl-noema-review2") == ()


@pytest.mark.parametrize(
    "payload",
    [
        event("no agent here"),
        event("@opencode-agent", association="CONTRIBUTOR"),
        event("@opencode-agent", user_type="Bot"),
        {**event("@opencode-agent"), "issue": {"number": 17}},
        {
            **event("@opencode-agent"),
            "pull_request": {
                **event("@opencode-agent")["pull_request"],
                "state": "closed",
            },
        },
        {
            **event("@opencode-agent"),
            "conversation_comments": [receipt(91)],
        },
    ],
)
def test_parse_event_ignores_untrusted_irrelevant_or_processed_comments(
    payload: dict,
) -> None:
    """Untrusted, irrelevant, non-PR, and acknowledged comments are ignored."""

    assert load_module().parse_event(payload) is None


def test_untrusted_receipt_marker_cannot_suppress_invocation() -> None:
    """A user-authored marker does not acknowledge a trusted invocation."""

    payload = event("@opencode-agent")
    payload["conversation_comments"] = [receipt(91, trusted=False)]
    assert load_module().parse_event(payload) is not None


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (("repository", "full_name"), "outside/example", "limited"),
        (("issue", "number"), 0, "number"),
        (("comment", "id"), 0, "comment id"),
        (("pull_request", "head", "sha"), "bad", "head SHA"),
        (("pull_request", "base", "ref"), "-bad", "base branch"),
        (("pull_request", "base", "sha"), "bad", "base SHA"),
        (("comment", "user", "login"), "", "actor"),
    ],
)
def test_parse_event_rejects_malformed_trusted_requests(
    path: tuple[str, ...],
    value: object,
    message: str,
) -> None:
    """Malformed trusted invocation metadata fails closed."""

    payload = event("@opencode-agent")
    target = payload
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ValueError, match=message):
        load_module().parse_event(payload)


def test_receipt_and_allowlist_helpers() -> None:
    """Receipt extraction and exact repository allowlists are deterministic."""

    module = load_module()
    assert module.receipt_marker(91) == "<!-- cwl-agent-mention-receipt:91 -->"
    with pytest.raises(ValueError, match="positive"):
        module.receipt_marker(0)
    comments = [
        receipt(91),
        {
            "body": "x <!-- cwl-agent-mention-receipt:92 --> y",
            "user": {"login": "github-actions[bot]", "type": "Bot"},
        },
        receipt(93, trusted=False),
        {"body": None, "user": {"login": "github-actions[bot]", "type": "Bot"}},
    ]
    assert module.processed_comment_ids(comments) == frozenset({91, 92})
    assert module.parse_repository_allowlist(
        "ContextualWisdomLab/example, ContextualWisdomLab/.github,"
    ) == frozenset(
        {"ContextualWisdomLab/example", "ContextualWisdomLab/.github"}
    )
    with pytest.raises(ValueError, match="invalid repository"):
        module.parse_repository_allowlist("outside/example")


def test_eligible_agents_and_payloads() -> None:
    """Eligibility and wrapper transport preserve the bounded review contract."""

    module = load_module()
    request = module.parse_event(event("@cwl-noema-review @opencode-agent"))
    assert request is not None
    assert module.eligible_agents(
        request,
        opencode_allowlist=frozenset({request.repository}),
    ) == (("cwl-noema-review", "opencode-agent"), ())
    assert module.eligible_agents(
        request,
        opencode_allowlist=frozenset(),
    ) == (("cwl-noema-review",), ("opencode-agent",))
    noema = module.noema_payload(request)
    assert noema["event_type"] == "agent-mention-noema"
    assert noema["client_payload"]["pr_head_sha"] == "a" * 40
    assert noema["client_payload"]["pr_base_sha"] == "b" * 40

    opencode = module.opencode_payload(request)
    assert opencode["event_type"] == "agent-mention-opencode"
    assert set(opencode["client_payload"]) == {
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
    assert len(opencode["client_payload"]) == 9
    assert opencode["client_payload"]["base_branch"] == "develop"
    assert opencode["client_payload"]["pr_base_sha"] == "b" * 40

    claim = module.agent_invocation_claim(request, "opencode-agent")
    assert claim["trigger_reviews"] is True
    assert claim["review_dispatch_limit"] == "1"
    assert claim["merge_mode"] == "disabled"
    assert claim["enable_auto_merge"] is False
    assert claim["update_branches"] is False


def test_dispatch_uses_central_events_and_acknowledges() -> None:
    """Both agents dispatch centrally with bounded review-only OpenCode options."""

    module = load_module()
    request = module.parse_event(event("@cwl-noema-review @opencode-agent"))
    assert request is not None
    target = FakeClient()
    central = FakeClient()
    result = module.dispatch_request(
        request,
        target_client=target,
        dispatch_client=central,
        opencode_allowlist=frozenset({request.repository}),
    )
    assert result == ("@cwl-noema-review", "@opencode-agent")
    dispatches = repository_dispatch_calls(central)
    assert [payload["event_type"] for _, payload in dispatches] == [
        "agent-mention-noema",
        "agent-mention-opencode",
    ]
    assert all(
        args[0] == "repos/ContextualWisdomLab/.github/dispatches"
        for args, _ in dispatches
    )
    assert len(dispatches[1][1]["client_payload"]) == 9
    assert target.calls[0][1] == {"content": "eyes"}
    assert "cwl-agent-mention-receipt:91" in target.calls[1][1]["body"]
    assert "exact-name Actions artifacts" in target.calls[1][1]["body"]


def test_dispatch_rejects_unallowlisted_opencode_and_supports_dry_run(
    capsys,
) -> None:
    """Rejected-only and dry-run requests remain mutation-free."""

    module = load_module()
    request = module.parse_event(event("@opencode-agent"))
    assert request is not None
    target = FakeClient()
    central = FakeClient()
    assert module.dispatch_request(
        request,
        target_client=target,
        dispatch_client=central,
        opencode_allowlist=frozenset(),
    ) == ()
    assert target.calls == central.calls == []
    assert "Rejected agent mention without target mutation" in capsys.readouterr().out

    target = FakeClient()
    central = FakeClient()
    assert module.dispatch_request(
        request,
        target_client=target,
        dispatch_client=central,
        opencode_allowlist=frozenset(),
        dry_run=True,
    ) == ()
    assert target.calls == central.calls == []
    output = capsys.readouterr().out
    assert "DRY-RUN agent mention" in output
    assert "reject=opencode-agent" in output


def test_dispatch_noema_only_covers_non_opencode_path() -> None:
    """A Noema-only request bypasses the OpenCode allowlist branch."""

    module = load_module()
    request = module.parse_event(event("@cwl-noema-review"))
    assert request is not None
    target = FakeClient()
    central = FakeClient()
    assert module.dispatch_request(
        request,
        target_client=target,
        dispatch_client=central,
        opencode_allowlist=frozenset(),
    ) == ("@cwl-noema-review",)
    dispatches = repository_dispatch_calls(central)
    assert len(dispatches) == 1
    assert dispatches[0][1]["event_type"] == "agent-mention-noema"


def test_github_client_validates_token_and_decodes_json(monkeypatch) -> None:
    """The token-bound client never places credentials in command arguments."""

    module = load_module()
    with pytest.raises(ValueError, match="token"):
        module.GitHubClient("")
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(stdout='{"ok": true}\n')

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    client = module.GitHubClient("secret-token")
    assert client.request(["repos/x/y"], input_payload={"a": 1}) == {"ok": True}
    command, kwargs = calls[0]
    assert command == ["gh", "api", "repos/x/y", "--input", "-"]
    assert "secret-token" not in command
    assert kwargs["env"]["GH_TOKEN"] == "secret-token"
    assert kwargs["input"] == '{"a": 1}'
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout="  "),
    )
    assert client.request(["repos/x/y"]) is None


def test_load_event_and_main_paths(tmp_path: Path, monkeypatch, capsys) -> None:
    """CLI rejects malformed JSON, ignores irrelevant events, and dispatches input."""

    module = load_module()
    array_path = tmp_path / "array.json"
    array_path.write_text(json.dumps(["bad"]), encoding="utf-8")
    with pytest.raises(ValueError, match="JSON object"):
        module.load_event(str(array_path))
    ignored_path = tmp_path / "ignored.json"
    ignored_path.write_text(json.dumps(event("nothing")), encoding="utf-8")
    assert module.main(["--event-path", str(ignored_path)]) == 0
    assert "nothing to dispatch" in capsys.readouterr().out
    monkeypatch.delenv("GITHUB_EVENT_PATH", raising=False)
    with pytest.raises(SystemExit):
        module.main([])
    valid_path = tmp_path / "valid.json"
    valid_path.write_text(json.dumps(event("@opencode-agent")), encoding="utf-8")
    captured = []
    monkeypatch.setenv("GH_TOKEN", "token")
    monkeypatch.setenv(
        "OPENCODE_REPOSITORY_DISPATCH_TARGETS",
        "ContextualWisdomLab/example",
    )
    monkeypatch.setattr(
        module,
        "dispatch_request",
        lambda request, **kwargs: captured.append((request, kwargs)) or (),
    )
    assert module.main(["--event-path", str(valid_path), "--dry-run"]) == 0
    assert captured[0][1]["dry_run"] is True
