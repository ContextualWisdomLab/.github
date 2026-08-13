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
    """Eligibility and event bodies preserve the bounded review contract."""

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
    assert opencode["client_payload"]["base_branch"] == "develop"
    assert opencode["client_payload"]["pr_base_sha"] == "b" * 40
    assert opencode["client_payload"]["review_contract"]["merge_mode"] == "disabled"
    assert opencode["client_payload"]["review_contract"]["enable_auto_merge"] is False
    assert opencode["client_payload"]["review_contract"]["update_branches"] is False


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


def review_comment_event(
    body: str = "@CWL-Noema-Review look at this line",
    *,
    association: str = "OWNER",
) -> dict:
    """Build a GitHub pull_request_review_comment webhook payload."""

    return {
        "action": "created",
        "comment": {
            "id": 224849228,
            "pull_request_review_id": 49019778,
            "body": body,
            "path": "scripts/ci/agent_mention_router.py",
            "line": 143,
            "commit_id": "a" * 40,
            "author_association": association,
            "user": {"login": "seonghobae", "type": "User"},
        },
        "pull_request": {
            "number": 953,
            "state": "open",
            "head": {"sha": "a" * 40},
            "base": {"ref": "main", "sha": "b" * 40},
        },
        "repository": {"full_name": "ContextualWisdomLab/.github"},
    }


def submitted_review_event(
    body: str = "@opencode-agent review this head",
    *,
    association: str = "MEMBER",
) -> dict:
    """Build a GitHub pull_request_review submitted webhook payload."""

    return {
        "action": "submitted",
        "review": {
            "id": 49019778,
            "body": body,
            "state": "COMMENTED",
            "submitted_at": "2026-08-13T04:12:00Z",
            "author_association": association,
            "user": {"login": "maintainer", "type": "User"},
        },
        "pull_request": {
            "number": 953,
            "state": "open",
            "head": {"sha": "a" * 40},
            "base": {"ref": "main", "sha": "b" * 40},
        },
        "repository": {"full_name": "ContextualWisdomLab/.github"},
    }


def test_parse_event_accepts_review_comments_and_submitted_reviews() -> None:
    """Line comments and review bodies dispatch without an issue.pull_request marker."""

    module = load_module()
    review_comment = module.parse_event(review_comment_event())
    assert review_comment is not None
    assert review_comment.agents == ("cwl-noema-review",)
    assert review_comment.pull_request_number == 953
    assert review_comment.comment_id == 224849228
    assert review_comment.source_kind == module.SOURCE_KIND_REVIEW_COMMENT
    assert review_comment.actor == "seonghobae"

    review = module.parse_event(submitted_review_event())
    assert review is not None
    assert review.agents == ("opencode-agent",)
    assert review.comment_id == 49019778
    assert review.source_kind == module.SOURCE_KIND_REVIEW

    assert module.parse_event({}) is None
    assert module.parse_event({"comment": {"id": 1, "body": "@opencode-agent"}}) is None
    assert module.mention_source({}) is None
    assert module.mention_source({"comment": "not-an-object", "review": 1}) is None
    pending = submitted_review_event()
    pending["review"]["state"] = "PENDING"
    assert module.parse_event(pending) is None
    dismissed = submitted_review_event()
    dismissed["review"]["state"] = "DISMISSED"
    assert module.parse_event(dismissed) is None


def test_parse_event_still_ignores_plain_issues_without_pull_request_marker() -> None:
    """An issue object without pull_request remains ignored even if a PR is attached."""

    payload = review_comment_event()
    payload["issue"] = {"number": 953}
    assert load_module().parse_event(payload) is None


def test_issue_comment_reaction_403_does_not_drop_a_queued_mention(
    capsys,
) -> None:
    """Live run 31670687388 died after dispatch on a 403 eyes reaction."""

    module = load_module()
    request = module.parse_event(event("@cwl-noema-review"))
    assert request is not None

    class ReactionForbiddenClient(FakeClient):
        """Raise the live GitHub App 403 only on the eyes reaction."""

        def request(self, args, *, input_payload=None):
            """Fail reactions the same way the installation token failed."""

            if any("reactions" in str(arg) for arg in args):
                raise RuntimeError(
                    "gh api failed with exit code 1: gh: Resource not "
                    "accessible by integration (HTTP 403)"
                )
            return super().request(args, input_payload=input_payload)

    target = ReactionForbiddenClient()
    central = FakeClient()
    assert module.dispatch_request(
        request,
        target_client=target,
        dispatch_client=central,
        opencode_allowlist=frozenset(),
    ) == ("@cwl-noema-review",)
    assert repository_dispatch_calls(central)
    assert any(
        args[0].endswith("/issues/17/comments") for args, _ in target.calls
    )
    assert "Could not add mention reaction" in capsys.readouterr().out
    assert module.add_mention_reaction(target, request) is False


def test_add_mention_reaction_only_targets_issue_comments() -> None:
    """Issue comments use the issue-comment reaction API."""

    module = load_module()
    issue_request = module.parse_event(event("@cwl-noema-review"))
    assert issue_request is not None
    client = FakeClient()
    assert module.add_mention_reaction(client, issue_request) is True
    assert client.calls[0][1] == {"content": "eyes"}
    assert "/issues/comments/" in client.calls[0][0][0]
    assert "/pulls/comments/" not in client.calls[0][0][0]


def test_add_mention_reaction_targets_review_comments() -> None:
    """Inline review comments use the pull-request review-comment reaction API."""

    module = load_module()
    review_request = module.parse_event(review_comment_event())
    assert review_request is not None
    client = FakeClient()
    assert module.add_mention_reaction(client, review_request) is True
    assert client.calls[0][1] == {"content": "eyes"}
    assert "/pulls/comments/" in client.calls[0][0][0]
    assert "/issues/comments/" not in client.calls[0][0][0]
    review_body = module.parse_event(submitted_review_event("@cwl-noema-review"))
    assert review_body is not None
    assert module.mention_reaction_path(review_body) is None

    class ReactionForbiddenClient(FakeClient):
        """Raise the live GitHub App 403 only on the eyes reaction."""

        def request(self, args, *, input_payload=None):
            """Fail reactions the same way the installation token failed."""

            if any("reactions" in str(arg) for arg in args):
                raise RuntimeError(
                    "gh api failed with exit code 1: gh: Resource not "
                    "accessible by integration (HTTP 403)"
                )
            return super().request(args, input_payload=input_payload)

    forbidden = ReactionForbiddenClient()
    assert module.add_mention_reaction(forbidden, review_request) is False


def test_add_mention_reaction_targets_submitted_review_bodies() -> None:
    """Submitted review bodies react through GraphQL addReaction, not REST comments."""

    module = load_module()
    review_request = module.parse_event(submitted_review_event("@cwl-noema-review"))
    assert review_request is not None

    class ReviewReactionClient(FakeClient):
        """Return a review node ID and record the GraphQL eyes mutation."""

        def request(self, args, *, input_payload=None):
            """Serve the review lookup, then record addReaction."""

            self.calls.append((list(args), input_payload))
            if args and "/reviews/" in str(args[0]):
                return {"node_id": "PRR_kwDOReviewBody"}
            if args and args[0] == "graphql":
                return {"data": {"addReaction": {"reaction": {"content": "EYES"}}}}
            return None

    client = ReviewReactionClient()
    assert module.add_mention_reaction(client, review_request) is True
    lookup, mutation = client.calls
    assert "/pulls/953/reviews/49019778" in lookup[0][0]
    assert mutation[0][0] == "graphql"
    assert mutation[1]["variables"]["id"] == "PRR_kwDOReviewBody"
    assert "addReaction" in mutation[1]["query"]

    class MissingNodeClient(FakeClient):
        """Return an empty review lookup so GraphQL is skipped."""

        def request(self, args, *, input_payload=None):
            """Record the lookup and return no node ID."""

            self.calls.append((list(args), input_payload))
            return {}

    assert module.add_mention_reaction(MissingNodeClient(), review_request) is False
    assert module.add_mention_reaction(FakeClient(), review_request) is False

    class EmptyNodeClient(FakeClient):
        """Return a blank review node ID."""

        def request(self, args, *, input_payload=None):
            """Record the lookup and return an unusable node ID."""

            self.calls.append((list(args), input_payload))
            return {"node_id": "   "}

    assert module.add_mention_reaction(EmptyNodeClient(), review_request) is False

    class IntNodeClient(FakeClient):
        """Return a non-string review node ID."""

        def request(self, args, *, input_payload=None):
            """Record the lookup and return a numeric node ID."""

            self.calls.append((list(args), input_payload))
            return {"node_id": 12}

    assert module.add_mention_reaction(IntNodeClient(), review_request) is False
    unknown = module.MentionRequest(
        repository="ContextualWisdomLab/.github",
        pull_request_number=953,
        pull_request_head_sha="a" * 40,
        pull_request_base_branch="main",
        comment_id=1,
        actor="maintainer",
        agents=("cwl-noema-review",),
        source_kind="unknown",
    )
    assert module.add_mention_reaction(FakeClient(), unknown) is False

    class ForbiddenGraphqlClient(ReviewReactionClient):
        """Raise the live GitHub App 403 on GraphQL addReaction."""

        def request(self, args, *, input_payload=None):
            """Fail GraphQL the same way the installation token failed."""

            if args and args[0] == "graphql":
                raise RuntimeError(
                    "gh api failed with exit code 1: gh: Resource not "
                    "accessible by integration (HTTP 403)"
                )
            return super().request(args, input_payload=input_payload)

    assert module.add_mention_reaction(ForbiddenGraphqlClient(), review_request) is False

    class GraphqlErrorClient(ReviewReactionClient):
        """Return a GraphQL error payload with HTTP 200."""

        def request(self, args, *, input_payload=None):
            """Record GraphQL errors without raising."""

            recorded = super().request(args, input_payload=input_payload)
            if args and args[0] == "graphql":
                return {"errors": [{"message": "Resource not accessible by integration"}]}
            return recorded

    assert module.add_mention_reaction(GraphqlErrorClient(), review_request) is False


def test_graphql_eyes_reaction_treats_already_reacted_as_success() -> None:
    """Already-reacted GraphQL errors are eyes on the review, not a miss."""

    module = load_module()
    assert module.graphql_error_already_reacted("nope") is False
    assert module.graphql_error_already_reacted({"code": "UNPROCESSABLE"}) is False
    assert (
        module.graphql_error_already_reacted(
            {"message": "Reaction already exists. You can only react once."}
        )
        is True
    )
    assert module.graphql_error_already_reacted({"message": "Resource not accessible"}) is False
    assert module.graphql_eyes_reaction_succeeded(None) is False
    assert module.graphql_eyes_reaction_succeeded({}) is False
    assert module.graphql_eyes_reaction_succeeded({"data": None}) is False
    assert module.graphql_eyes_reaction_succeeded({"data": {"addReaction": None}}) is False
    assert (
        module.graphql_eyes_reaction_succeeded(
            {"data": {"addReaction": {"reaction": None}}}
        )
        is False
    )
    assert (
        module.graphql_eyes_reaction_succeeded(
            {"data": {"addReaction": {"reaction": {"content": 1}}}}
        )
        is False
    )
    assert (
        module.graphql_eyes_reaction_succeeded(
            {"data": {"addReaction": {"reaction": {"content": "EYES"}}}}
        )
        is True
    )
    assert (
        module.graphql_eyes_reaction_succeeded(
            {
                "errors": [
                    {"message": "You've already reacted with this emoji"},
                ]
            }
        )
        is True
    )
    assert (
        module.graphql_eyes_reaction_succeeded(
            {
                "errors": [
                    {"message": "You've already reacted with this emoji"},
                    {"message": "Resource not accessible by integration"},
                ]
            }
        )
        is False
    )
    assert (
        module.graphql_eyes_reaction_succeeded(
            {"errors": ["not-an-object", {"message": "already reacted"}]}
        )
        is False
    )

    review_request = module.parse_event(submitted_review_event("@cwl-noema-review"))
    assert review_request is not None

    class AlreadyReactedClient(FakeClient):
        """Return the live already-reacted GraphQL body."""

        def request(self, args, *, input_payload=None):
            """Serve the review lookup, then the already-reacted error."""

            self.calls.append((list(args), input_payload))
            if args and "/reviews/" in str(args[0]):
                return {"node_id": "PRR_kwDOReviewBody"}
            if args and args[0] == "graphql":
                return {
                    "data": {"addReaction": None},
                    "errors": [
                        {"message": "You've already reacted with this emoji"},
                    ],
                }
            return None

    assert module.add_mention_reaction(AlreadyReactedClient(), review_request) is True

    class EmptyGraphqlClient(FakeClient):
        """Return a 200 GraphQL body with no addReaction payload."""

        def request(self, args, *, input_payload=None):
            """Serve the review lookup, then an empty GraphQL object."""

            self.calls.append((list(args), input_payload))
            if args and "/reviews/" in str(args[0]):
                return {"node_id": "PRR_kwDOReviewBody"}
            if args and args[0] == "graphql":
                return {}
            return None

    assert module.add_mention_reaction(EmptyGraphqlClient(), review_request) is False


def test_dispatch_review_surfaces_skip_issue_comment_reactions() -> None:
    """Review-comment dispatch reacts on the review-comment endpoint, not issue comments."""

    module = load_module()
    request = module.parse_event(review_comment_event())
    assert request is not None
    target = FakeClient()
    central = FakeClient()
    assert module.dispatch_request(
        request,
        target_client=target,
        dispatch_client=central,
        opencode_allowlist=frozenset(),
    ) == ("@cwl-noema-review",)
    reaction_calls = [
        args[0] for args, _ in target.calls if "reactions" in args[0]
    ]
    assert reaction_calls
    assert all("/pulls/comments/" in path for path in reaction_calls)
    assert all("/issues/comments/" not in path for path in reaction_calls)
    assert any(
        args[0].endswith("/issues/953/comments") for args, _ in target.calls
    )

    review_request = module.parse_event(submitted_review_event("@cwl-noema-review"))
    assert review_request is not None

    class ReviewDispatchClient(FakeClient):
        """Return a review node ID so dispatch can post GraphQL eyes."""

        def request(self, args, *, input_payload=None):
            """Serve review lookup and record later mutations."""

            self.calls.append((list(args), input_payload))
            if args and "/reviews/" in str(args[0]):
                return {"node_id": "PRR_kwDOReviewBody"}
            if args and args[0] == "graphql":
                return {"data": {"addReaction": {"reaction": {"content": "EYES"}}}}
            return None

    review_target = ReviewDispatchClient()
    assert module.dispatch_request(
        review_request,
        target_client=review_target,
        dispatch_client=FakeClient(),
        opencode_allowlist=frozenset(),
    ) == ("@cwl-noema-review",)
    assert any(args[0] == "graphql" for args, _ in review_target.calls)
    assert all("/issues/comments/" not in args[0] for args, _ in review_target.calls)
