"""Tests for organization-wide pull-request comment mention sweeping."""

from __future__ import annotations

import importlib
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts" / "ci"
sys.path.insert(0, str(SCRIPTS))


class FakeClient:
    """Endpoint-keyed fake GitHub client for sweep tests."""

    def __init__(self, responses=None) -> None:
        """Initialize response mapping and request ledger."""

        self.responses = responses or {}
        self.calls = []

    def request(self, args, *, input_payload=None):
        """Return the response registered for the first API argument."""

        self.calls.append((list(args), input_payload))
        return self.responses.get(args[0])


def comment(
    comment_id: int,
    body: str,
    *,
    association: str = "MEMBER",
    user_type: str = "User",
    login: str = "maintainer",
) -> dict:
    """Build one issue-comment API object."""

    return {
        "id": comment_id,
        "body": body,
        "author_association": association,
        "user": {"login": login, "type": user_type},
    }


def repository(
    name: str = "example",
    *,
    owner: str = "ContextualWisdomLab",
    archived: bool = False,
    disabled: bool = False,
) -> dict:
    """Build one repository API object."""

    return {
        "full_name": f"{owner}/{name}",
        "owner": {"login": owner},
        "archived": archived,
        "disabled": disabled,
    }


def candidate(number: int = 7) -> dict:
    """Build one normalized pull-request candidate."""

    return {
        "number": number,
        "repository": "ContextualWisdomLab/example",
        "pull_request": {
            "url": (
                "https://api.github.com/repos/ContextualWisdomLab/example/"
                f"pulls/{number}"
            )
        },
    }


def pull_list_item(number: int = 7, updated_at: str = "2026-08-05T11:00:00Z") -> dict:
    """Build one pull-list API item."""

    return {"number": number, "updated_at": updated_at}


def live_pull(state: str = "open") -> dict:
    """Build live pull-request metadata consumed by the router."""

    return {
        "state": state,
        "head": {"sha": "b" * 40},
        "base": {"ref": "main", "sha": "c" * 40},
    }


def module():
    """Reload the sweep module for isolated monkeypatching."""

    return importlib.reload(importlib.import_module("agent_mention_sweep"))


def test_timestamp_cutoff_and_page_validation() -> None:
    """Timestamps, lookback bounds, and pagination fail closed."""

    sweep = module()
    now = datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc)
    assert sweep.parse_timestamp("2026-08-05T11:00:00Z") == datetime(
        2026,
        8,
        5,
        11,
        0,
        tzinfo=timezone.utc,
    )
    for invalid in ("bad", "2026-08-05T11:00:00"):
        with pytest.raises(ValueError, match="timestamp"):
            sweep.parse_timestamp(invalid)
    assert sweep.cutoff_timestamp(24, now=now) == "2026-08-04T12:00:00Z"
    for hours in (0, 721):
        with pytest.raises(ValueError, match="lookback"):
            sweep.cutoff_timestamp(hours, now=now)
    with pytest.raises(ValueError, match="timezone-aware"):
        sweep.cutoff_timestamp(1, now=datetime(2026, 8, 5))
    assert sweep.flatten_pages([[{"a": 1}], [{"b": 2}]]) == [
        {"a": 1},
        {"b": 2},
    ]
    assert sweep.flatten_pages(
        [{"items": [{"a": 1}]}], collection_key="items"
    ) == [{"a": 1}]
    with pytest.raises(ValueError, match="empty"):
        sweep.flatten_pages(None)
    with pytest.raises(ValueError, match="page is not an object"):
        sweep.flatten_pages([[]], collection_key="items")
    with pytest.raises(ValueError, match="not a list"):
        sweep.flatten_pages({"items": {}}, collection_key="items")
    with pytest.raises(ValueError, match="non-object"):
        sweep.flatten_pages([[1]])


def test_accessible_repository_sources_filter_and_validate() -> None:
    """PAT and installation-token repository inventories are both supported."""

    sweep = module()
    organization_response = [[
        repository(),
        repository("archived", archived=True),
        repository("disabled", disabled=True),
        repository("outside", owner="outside"),
    ]]
    organization_client = FakeClient(
        {"orgs/ContextualWisdomLab/repos": organization_response}
    )
    assert sweep.list_accessible_repositories(
        organization_client,
        organization="ContextualWisdomLab",
        repository_source="organization",
    ) == ["ContextualWisdomLab/example"]
    installation_client = FakeClient(
        {
            "installation/repositories": [
                {"repositories": [repository(), repository("second")]}
            ]
        }
    )
    assert sweep.list_accessible_repositories(
        installation_client,
        organization="ContextualWisdomLab",
        repository_source="installation",
    ) == ["ContextualWisdomLab/example", "ContextualWisdomLab/second"]
    with pytest.raises(ValueError, match="organization"):
        sweep.list_accessible_repositories(
            organization_client,
            organization="bad/name",
            repository_source="organization",
        )
    with pytest.raises(ValueError, match="repository source"):
        sweep.list_accessible_repositories(
            organization_client,
            organization="ContextualWisdomLab",
            repository_source="bad",
        )
    invalid_client = FakeClient(
        {
            "orgs/ContextualWisdomLab/repos": [[
                {**repository(), "full_name": "bad/name"}
            ]]
        }
    )
    with pytest.raises(ValueError, match="full_name"):
        sweep.list_accessible_repositories(
            invalid_client,
            organization="ContextualWisdomLab",
            repository_source="organization",
        )


def test_recent_pull_request_filtering() -> None:
    """Only open accessible PRs updated at or after the cutoff are yielded."""

    sweep = module()
    client = FakeClient(
        {
            "orgs/ContextualWisdomLab/repos": [[repository()]],
            "repos/ContextualWisdomLab/example/pulls": [[
                pull_list_item(7, "2026-08-05T11:00:00Z"),
                pull_list_item(8, "2026-08-04T11:59:59Z"),
            ]],
        }
    )
    assert list(
        sweep.list_recent_pull_requests(
            client,
            organization="ContextualWisdomLab",
            repository_source="organization",
            since="2026-08-04T12:00:00Z",
        )
    ) == [candidate()]
    bad_number_client = FakeClient(
        {
            "orgs/ContextualWisdomLab/repos": [[repository()]],
            "repos/ContextualWisdomLab/example/pulls": [[
                {"number": 0, "updated_at": "2026-08-05T11:00:00Z"}
            ]],
        }
    )
    with pytest.raises(ValueError, match="pull request number"):
        list(
            sweep.list_recent_pull_requests(
                bad_number_client,
                organization="ContextualWisdomLab",
                repository_source="organization",
                since="2026-08-04T12:00:00Z",
            )
        )


def test_build_requests_ignores_receipt_markers_and_skips_closed_pulls() -> None:
    """Target comments are context only; trusted live mentions remain requests."""

    sweep = module()
    comments_endpoint = "repos/ContextualWisdomLab/example/issues/7/comments"
    review_comments_endpoint = "repos/ContextualWisdomLab/example/pulls/7/comments"
    reviews_endpoint = "repos/ContextualWisdomLab/example/pulls/7/reviews"
    pull_endpoint = "repos/ContextualWisdomLab/example/pulls/7"
    comments = [
        comment(10, "@opencode-agent"),
        comment(
            11,
            "<!-- cwl-agent-mention-receipt:10 -->",
            user_type="Bot",
            login="github-actions[bot]",
        ),
        comment(12, "@cwl-noema-review"),
        comment(13, "@opencode-agent", association="CONTRIBUTOR"),
    ]
    client = FakeClient(
        {
            comments_endpoint: [comments],
            review_comments_endpoint: [[]],
            reviews_endpoint: [[]],
            pull_endpoint: live_pull(),
        }
    )
    requests = sweep.build_requests_for_pull_request(
        client, issue=candidate(), since="2026-08-04T00:00:00Z"
    )
    assert [request.comment_id for request in requests] == [10, 12]
    assert [request.agents for request in requests] == [
        ("opencode-agent",),
        ("cwl-noema-review",),
    ]
    assert {request.pull_request_base_sha for request in requests} == {"c" * 40}
    closed = FakeClient(
        {
            comments_endpoint: [comments],
            review_comments_endpoint: [[]],
            reviews_endpoint: [[]],
            pull_endpoint: live_pull("closed"),
        }
    )
    assert (
        sweep.build_requests_for_pull_request(
            closed, issue=candidate(), since="2026-08-04T00:00:00Z"
        )
        == ()
    )
    with pytest.raises(ValueError, match="repository"):
        sweep.build_requests_for_pull_request(
            client, issue={**candidate(), "repository": "bad/name"}, since="x"
        )
    with pytest.raises(ValueError, match="number"):
        sweep.build_requests_for_pull_request(
            client, issue={**candidate(), "number": 0}, since="x"
        )


def mention_request(number: int, comment_id: int, agent: str):
    """Build one validated router request for orchestration tests."""

    router = importlib.import_module("agent_mention_router")
    return router.MentionRequest(
        "ContextualWisdomLab/example",
        number,
        "a" * 40,
        "main",
        comment_id,
        "maintainer",
        (agent,),
        pull_request_base_sha="b" * 40,
    )


def test_sweep_dispatches_with_limit_and_reports_empty(monkeypatch, capsys) -> None:
    """The sweep bounds source requests that actually queue new agent work."""

    sweep = module()
    request_a = mention_request(7, 10, "opencode-agent")
    request_b = mention_request(8, 11, "cwl-noema-review")
    monkeypatch.setattr(
        sweep, "list_recent_pull_requests", lambda *args, **kwargs: iter([candidate()])
    )
    monkeypatch.setattr(
        sweep,
        "build_requests_for_pull_request",
        lambda *args, **kwargs: (request_a, request_b),
    )
    dispatch_calls = []

    def dispatch_new_work(request, **kwargs):
        """Record one call and report its newly queued agent handle."""

        dispatch_calls.append(request.comment_id)
        return (f"@{request.agents[0]}",)

    monkeypatch.setattr(sweep, "dispatch_request", dispatch_new_work)
    assert (
        sweep.sweep(
            target_client=FakeClient(),
            dispatch_client=FakeClient(),
            organization="ContextualWisdomLab",
            repository_source="organization",
            lookback_hours=24,
            max_dispatches=1,
            opencode_allowlist=frozenset({"ContextualWisdomLab/example"}),
            now=datetime(2026, 8, 5, tzinfo=timezone.utc),
        )
        == 1
    )
    assert dispatch_calls == [10]
    assert "reached dispatch limit" in capsys.readouterr().out
    monkeypatch.setattr(
        sweep, "list_recent_pull_requests", lambda *args, **kwargs: iter(())
    )
    assert (
        sweep.sweep(
            target_client=FakeClient(),
            dispatch_client=FakeClient(),
            organization="ContextualWisdomLab",
            repository_source="installation",
            lookback_hours=24,
            max_dispatches=2,
            opencode_allowlist=frozenset(),
            now=datetime(2026, 8, 5, tzinfo=timezone.utc),
        )
        == 0
    )
    assert "0 dispatch" in capsys.readouterr().out
    for value in (0, 101):
        with pytest.raises(ValueError, match="max dispatches"):
            sweep.sweep(
                target_client=FakeClient(),
                dispatch_client=FakeClient(),
                organization="ContextualWisdomLab",
                repository_source="organization",
                lookback_hours=24,
                max_dispatches=value,
                opencode_allowlist=frozenset(),
            )


def test_sweep_noops_do_not_starve_new_mentions_across_repeated_runs(
    monkeypatch,
) -> None:
    """Already-ledgered requests never consume the bounded new-work budget."""

    sweep = module()
    historical = tuple(
        mention_request(7, comment_id, "opencode-agent")
        for comment_id in range(100, 121)
    )
    new_request = mention_request(7, 999, "opencode-agent")
    requests = (*historical, new_request)
    monkeypatch.setattr(
        sweep, "list_recent_pull_requests", lambda *args, **kwargs: iter([candidate()])
    )
    monkeypatch.setattr(
        sweep,
        "build_requests_for_pull_request",
        lambda *args, **kwargs: requests,
    )
    ledgered_comment_ids = {request.comment_id for request in historical}
    dispatch_calls = []

    def dispatch_from_ledger(request, **kwargs):
        """Return work only for a source request absent from the durable ledger."""

        dispatch_calls.append(request.comment_id)
        if request.comment_id in ledgered_comment_ids:
            return ()
        ledgered_comment_ids.add(request.comment_id)
        return ("@opencode-agent",)

    monkeypatch.setattr(sweep, "dispatch_request", dispatch_from_ledger)
    sweep_kwargs = {
        "target_client": FakeClient(),
        "dispatch_client": FakeClient(),
        "organization": "ContextualWisdomLab",
        "repository_source": "organization",
        "lookback_hours": 168,
        "max_dispatches": 1,
        "opencode_allowlist": frozenset({"ContextualWisdomLab/example"}),
        "now": datetime(2026, 8, 5, tzinfo=timezone.utc),
    }

    assert sweep.sweep(**sweep_kwargs) == 1
    assert dispatch_calls == [request.comment_id for request in requests]
    dispatch_calls.clear()

    assert sweep.sweep(**sweep_kwargs) == 0
    assert dispatch_calls == [request.comment_id for request in requests]


def test_sweep_continues_across_empty_results_and_completes(
    monkeypatch, capsys
) -> None:
    """Empty candidate results do not stop later PR processing."""

    sweep = module()
    request = mention_request(8, 12, "cwl-noema-review")
    monkeypatch.setattr(
        sweep,
        "list_recent_pull_requests",
        lambda *args, **kwargs: iter([candidate(), candidate(8)]),
    )
    monkeypatch.setattr(
        sweep,
        "build_requests_for_pull_request",
        lambda *args, issue, **kwargs: () if issue["number"] == 7 else (request,),
    )
    dispatch_calls = []

    def dispatch_new_work(request, **kwargs):
        """Record and report the one newly queued review agent."""

        dispatch_calls.append(request.comment_id)
        return ("@cwl-noema-review",)

    monkeypatch.setattr(sweep, "dispatch_request", dispatch_new_work)
    assert (
        sweep.sweep(
            target_client=FakeClient(),
            dispatch_client=FakeClient(),
            organization="ContextualWisdomLab",
            repository_source="organization",
            lookback_hours=24,
            max_dispatches=2,
            opencode_allowlist=frozenset(),
            now=datetime(2026, 8, 5, tzinfo=timezone.utc),
        )
        == 1
    )
    assert dispatch_calls == [12]
    assert "completed with 1 dispatch" in capsys.readouterr().out


def test_main_constructs_clients_and_forwards_options(monkeypatch) -> None:
    """CLI reads credentials, parses allowlist, and forwards bounded options."""

    sweep = module()
    captured = []
    monkeypatch.setenv("TARGET_REPOSITORY_TOKEN", "target")
    monkeypatch.setenv("AGENT_DISPATCH_TOKEN", "dispatch")
    monkeypatch.setenv(
        "OPENCODE_REPOSITORY_DISPATCH_TARGETS", "ContextualWisdomLab/example"
    )
    monkeypatch.setattr(sweep, "sweep", lambda **kwargs: captured.append(kwargs) or 0)
    assert (
        sweep.main(
            [
                "--organization",
                "ContextualWisdomLab",
                "--repository-source",
                "installation",
                "--lookback-hours",
                "48",
                "--max-dispatches",
                "3",
                "--dry-run",
            ]
        )
        == 0
    )
    assert captured[0]["repository_source"] == "installation"
    assert captured[0]["lookback_hours"] == 48
    assert captured[0]["max_dispatches"] == 3
    assert captured[0]["dry_run"] is True


def test_build_requests_includes_review_comments_and_submitted_reviews() -> None:
    """Sweep surfaces line comments and review bodies that issue comments miss."""

    sweep = module()
    comments_endpoint = "repos/ContextualWisdomLab/example/issues/7/comments"
    review_comments_endpoint = "repos/ContextualWisdomLab/example/pulls/7/comments"
    reviews_endpoint = "repos/ContextualWisdomLab/example/pulls/7/reviews"
    pull_endpoint = "repos/ContextualWisdomLab/example/pulls/7"
    ignored_review_comment = comment(224849227, "no agent handle here")
    ignored_review = {
        "id": 10,
        "body": "@opencode-agent contributor cannot dispatch",
        "state": "COMMENTED",
        "submitted_at": "2026-08-05T11:00:00Z",
        "author_association": "CONTRIBUTOR",
        "user": {"login": "outsider", "type": "User"},
    }
    review_comment = comment(
        224849228,
        "@CWL-Noema-Review please inspect this hunk",
        association="OWNER",
        login="seonghobae",
    )
    review_comment["pull_request_review_id"] = 49019778
    review_comment["path"] = "scripts/ci/agent_mention_router.py"
    review_comment["line"] = 143
    submitted_review = {
        "id": 49019778,
        "body": "@opencode-agent review this exact head",
        "state": "COMMENTED",
        "submitted_at": "2026-08-05T11:30:00Z",
        "author_association": "MEMBER",
        "user": {"login": "maintainer", "type": "User"},
    }
    pending_review = {
        "id": 11,
        "body": "@opencode-agent pending should not dispatch",
        "state": "PENDING",
        "author_association": "OWNER",
        "user": {"login": "seonghobae", "type": "User"},
    }
    dismissed_review = {
        "id": 13,
        "body": "@opencode-agent dismissed should not dispatch",
        "state": "DISMISSED",
        "submitted_at": "2026-08-05T11:45:00Z",
        "author_association": "MEMBER",
        "user": {"login": "maintainer", "type": "User"},
    }
    uncommented_without_submission = {
        "id": 14,
        "body": "@opencode-agent missing submitted_at",
        "state": "COMMENTED",
        "author_association": "MEMBER",
        "user": {"login": "maintainer", "type": "User"},
    }
    stale_review = {
        "id": 12,
        "body": "@cwl-noema-review stale review",
        "state": "COMMENTED",
        "submitted_at": "2026-07-01T00:00:00Z",
        "author_association": "OWNER",
        "user": {"login": "seonghobae", "type": "User"},
    }
    client = FakeClient(
        {
            comments_endpoint: [[]],
            review_comments_endpoint: [[ignored_review_comment, review_comment]],
            reviews_endpoint: [
                [
                    ignored_review,
                    submitted_review,
                    pending_review,
                    dismissed_review,
                    uncommented_without_submission,
                    stale_review,
                ]
            ],
            pull_endpoint: live_pull(),
        }
    )
    requests = sweep.build_requests_for_pull_request(
        client, issue=candidate(), since="2026-08-04T00:00:00Z"
    )
    assert [request.comment_id for request in requests] == [224849228, 49019778]
    assert [request.agents for request in requests] == [
        ("cwl-noema-review",),
        ("opencode-agent",),
    ]
    assert [request.source_kind for request in requests] == [
        "review_comment",
        "review",
    ]
    assert [request.pull_request_number for request in requests] == [7, 7]


def test_list_recent_reviews_rejects_invalid_submission_timestamps() -> None:
    """A review inventory with a malformed submitted_at fails closed."""

    sweep = module()
    client = FakeClient(
        {
            "repos/ContextualWisdomLab/example/pulls/7/reviews": [
                [
                    {
                        "id": 1,
                        "body": "@cwl-noema-review",
                        "submitted_at": "not-a-timestamp",
                    }
                ]
            ]
        }
    )
    with pytest.raises(ValueError, match="timestamp"):
        sweep.list_recent_reviews(
            client,
            repository="ContextualWisdomLab/example",
            pull_request_number=7,
            since="2026-08-04T00:00:00Z",
        )
