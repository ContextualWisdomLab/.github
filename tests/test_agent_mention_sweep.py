"""Tests for organization-wide pull-request comment mention sweeping."""

from __future__ import annotations

import concurrent.futures
import importlib
import sys
import threading
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
    assert sweep.flatten_pages([{"items": [{"a": 1}]}], collection_key="items") == [
        {"a": 1}
    ]
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
    organization_response = [
        [
            repository(),
            repository("archived", archived=True),
            repository("disabled", disabled=True),
            repository("outside", owner="outside"),
        ]
    ]
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
            "orgs/ContextualWisdomLab/repos": [
                [{**repository(), "full_name": "bad/name"}]
            ]
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
            "repos/ContextualWisdomLab/example/pulls": [
                [
                    pull_list_item(7, "2026-08-05T11:00:00Z"),
                    pull_list_item(8, "2026-08-04T11:59:59Z"),
                ]
            ],
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
            "repos/ContextualWisdomLab/example/pulls": [
                [{"number": 0, "updated_at": "2026-08-05T11:00:00Z"}]
            ],
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
    client = FakeClient({comments_endpoint: [comments], pull_endpoint: live_pull()})
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
        {comments_endpoint: [comments], pull_endpoint: live_pull("closed")}
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


def test_sweep_closes_pull_iterator_at_dispatch_limit(monkeypatch) -> None:
    """Reaching the work limit explicitly closes repository collection."""

    sweep = module()

    class PullIterator:
        """Expose whether the sweep closes its candidate source."""

        def __init__(self) -> None:
            self.closed = False
            self.sent = False

        def __iter__(self):
            return self

        def __next__(self):
            if self.sent:
                raise StopIteration
            self.sent = True
            return candidate()

        def close(self) -> None:
            self.closed = True

    source = PullIterator()
    request = mention_request(7, 10, "opencode-agent")
    monkeypatch.setattr(
        sweep, "list_recent_pull_requests", lambda *args, **kwargs: source
    )
    monkeypatch.setattr(
        sweep,
        "build_requests_for_pull_request",
        lambda *args, **kwargs: (request,),
    )
    monkeypatch.setattr(
        sweep, "dispatch_request", lambda *args, **kwargs: ("@opencode-agent",)
    )

    assert (
        sweep.sweep(
            target_client=FakeClient(),
            dispatch_client=FakeClient(),
            organization="ContextualWisdomLab",
            repository_source="organization",
            lookback_hours=24,
            max_dispatches=1,
            opencode_allowlist=frozenset(),
            now=datetime(2026, 8, 5, tzinfo=timezone.utc),
        )
        == 1
    )
    assert source.closed is True


def test_closing_concurrent_collection_cancels_pending_repository_work(
    monkeypatch,
) -> None:
    """Closing a partial result stops running work and cancels queued futures."""

    sweep = module()

    class FakeFuture:
        """Run one submitted call on demand for deterministic scheduling."""

        def __init__(self, function, arguments) -> None:
            self.function = function
            self.arguments = arguments
            self.cancelled = False
            self.executed = False

        def result(self):
            self.executed = True
            return self.function(*self.arguments)

    class FakeExecutor:
        """Record the shutdown contract and model one running worker."""

        instance = None

        def __init__(self, *, max_workers) -> None:
            self.max_workers = max_workers
            self.futures = []
            self.shutdown_call = None
            FakeExecutor.instance = self

        def submit(self, function, *arguments):
            future = FakeFuture(function, arguments)
            self.futures.append(future)
            return future

        def shutdown(self, *, wait, cancel_futures=False) -> None:
            self.shutdown_call = (wait, cancel_futures)
            if not wait:
                # A task that was already running observes the shared stop
                # signal before issuing its first page request.
                self.futures[1].result()
                for future in self.futures[2:]:
                    future.cancelled = True

    monkeypatch.setattr(concurrent.futures, "ThreadPoolExecutor", FakeExecutor)
    client = FakeClient(
        {
            "orgs/ContextualWisdomLab/repos": [
                [repository("first"), repository("running"), repository("queued")]
            ],
            "repos/ContextualWisdomLab/first/pulls": [
                pull_list_item(1, "2026-08-05T11:00:00Z")
            ],
        }
    )
    candidates = sweep.list_recent_pull_requests(
        client,
        organization="ContextualWisdomLab",
        repository_source="organization",
        since="2026-08-05T10:00:00Z",
    )

    assert next(candidates)["number"] == 1
    candidates.close()

    executor = FakeExecutor.instance
    assert executor.max_workers == 3
    assert executor.shutdown_call == (False, True)
    assert executor.futures[1].executed is True
    assert executor.futures[2].cancelled is True
    assert [call[0][0] for call in client.calls] == [
        "orgs/ContextualWisdomLab/repos",
        "repos/ContextualWisdomLab/first/pulls",
    ]


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


def test_list_recent_pull_requests_concurrent_multiple_repositories():
    """Testing N+1 API block solution branch where multiple repositories are checked concurrently."""
    sweep = module()

    class SmartFakeClient(FakeClient):
        def __init__(self, responses, explode_repos=False):
            super().__init__(responses)
            self.explode_repos = explode_repos

        def request(self, args, *, input_payload=None):
            if self.explode_repos and args[0].startswith("repos/"):
                raise ValueError("Simulated Exception")
            return super().request(args, input_payload=input_payload)

    client = SmartFakeClient(
        {
            "orgs/ContextualWisdomLab/repos": [
                [
                    repository(name="example1"),
                    repository(name="example2"),
                ]
            ],
            "repos/ContextualWisdomLab/example1/pulls": [
                [pull_list_item(number=1, updated_at="2026-08-05T11:00:00Z")]
            ],
            "repos/ContextualWisdomLab/example2/pulls": [
                [pull_list_item(number=2, updated_at="2026-08-05T11:00:00Z")]
            ],
        }
    )
    pulls = list(
        sweep.list_recent_pull_requests(
            client,
            organization="ContextualWisdomLab",
            repository_source="organization",
            since="2026-08-05T10:00:00Z",
        )
    )
    assert len(pulls) == 2
    assert {p["number"] for p in pulls} == {1, 2}

    # Test error handling logic inside fetch_repo_pulls
    error_client = SmartFakeClient(
        {
            "orgs/ContextualWisdomLab/repos": [
                [
                    repository(name="example1"),
                    repository(name="example2"),
                ]
            ],
        },
        explode_repos=True,
    )

    metrics = sweep.SweepMetrics()
    dispatched = sweep.sweep(
        target_client=error_client,
        dispatch_client=error_client,
        organization="ContextualWisdomLab",
        repository_source="organization",
        lookback_hours=1,
        max_dispatches=10,
        opencode_allowlist=frozenset(),
        dry_run=True,
        now=datetime(2026, 8, 5, 11, 0, tzinfo=timezone.utc),
        metrics=metrics,
    )
    assert dispatched == 0
    assert metrics.failures == 2  # One failure per repository


def test_concurrent_repository_errors_are_reported_serially_in_source_order() -> None:
    """Worker failures reach the caller callback in repository order on its thread."""
    sweep = module()
    caller_thread = threading.get_ident()
    barrier = threading.Barrier(2)

    class ConcurrentFailureClient(FakeClient):
        def request(self, args, *, input_payload=None):
            if args[0] == "orgs/ContextualWisdomLab/repos":
                return [[repository("first"), repository("second")]]
            barrier.wait(timeout=2)
            raise ValueError(args[0])

    failures = []
    assert list(
        sweep.list_recent_pull_requests(
            ConcurrentFailureClient(),
            organization="ContextualWisdomLab",
            repository_source="organization",
            since="2026-08-05T10:00:00Z",
            on_error=lambda name, error: failures.append(
                (name, str(error), threading.get_ident())
            ),
        )
    ) == []

    assert [name for name, _error, _thread in failures] == [
        "ContextualWisdomLab/first",
        "ContextualWisdomLab/second",
    ]
    assert {thread for _name, _error, thread in failures} == {caller_thread}


def test_sweep_failures_during_processing(monkeypatch, capsys) -> None:
    """Sweep gracefully isolates exceptions during request building and dispatching."""
    sweep = module()
    client = FakeClient(
        {
            "orgs/ContextualWisdomLab/repos": [[repository()]],
            "repos/ContextualWisdomLab/example/pulls": [
                [pull_list_item(number=1), pull_list_item(number=2)]
            ],
        }
    )

    def fail_build(*args, **kwargs):
        if kwargs.get("issue", {}).get("number") == 1:
            raise ValueError("Build Error")
        return [mention_request(2, 20, "opencode-agent")]

    monkeypatch.setattr(sweep, "build_requests_for_pull_request", fail_build)

    def fail_dispatch(*args, **kwargs):
        raise ValueError("Dispatch Error")

    monkeypatch.setattr(sweep, "dispatch_request", fail_dispatch)

    metrics = sweep.SweepMetrics()
    sweep.sweep(
        target_client=client,
        dispatch_client=client,
        organization="ContextualWisdomLab",
        repository_source="organization",
        lookback_hours=1,
        max_dispatches=10,
        opencode_allowlist=frozenset(),
        now=datetime(2026, 8, 5, 11, 0, tzinfo=timezone.utc),
        metrics=metrics,
    )
    assert metrics.failures == 2  # One for PR 1 build fail, one for PR 2 dispatch fail


def test_pagination_break_without_cutoff() -> None:
    """Pagination terminates gracefully when less than 100 items are returned."""
    sweep = module()
    client = FakeClient(
        {
            "orgs/ContextualWisdomLab/repos": [[repository()]],
            "repos/ContextualWisdomLab/example/pulls": [
                [pull_list_item(number=1, updated_at="2026-08-05T11:00:00Z")],
                [],  # Page 2 returns empty list
            ],
        }
    )
    pulls = list(
        sweep.list_recent_pull_requests(
            client,
            organization="ContextualWisdomLab",
            repository_source="organization",
            since="2026-08-05T10:00:00Z",
        )
    )
    assert len(pulls) == 1


def test_pagination_empty_page_loop_break() -> None:
    """Pagination terminates when an empty list of pull requests is returned without exceptions."""
    sweep = module()
    client = FakeClient(
        {
            "orgs/ContextualWisdomLab/repos": [[repository()]],
            "repos/ContextualWisdomLab/example/pulls": [[]],
        }
    )
    pulls = list(
        sweep.list_recent_pull_requests(
            client,
            organization="ContextualWisdomLab",
            repository_source="organization",
            since="2026-08-05T10:00:00Z",
        )
    )
    assert len(pulls) == 0


def test_accessible_repository_invalid_repo_name() -> None:
    """Accessible repository invalid name check."""
    sweep = module()
    organization_response = [
        [
            {
                "full_name": "ContextualWisdomLab/invalid name with spaces",
                "owner": {"login": "ContextualWisdomLab"},
                "archived": False,
                "disabled": False,
            }
        ]
    ]
    client = FakeClient({"orgs/ContextualWisdomLab/repos": organization_response})
    import pytest

    with pytest.raises(ValueError, match="invalid repository full_name"):
        sweep.list_accessible_repositories(
            client, organization="ContextualWisdomLab", repository_source="organization"
        )


def test_flatten_pages_direct_list_return():
    """Flatten pages handles direct list of dicts properly."""
    sweep = module()
    direct_list = [{"foo": "bar"}, {"baz": "qux"}]
    assert sweep.flatten_pages(direct_list) == direct_list


def test_list_recent_pull_requests_multiple_pages():
    """Pagination fetches multiple pages correctly without errors."""
    sweep = module()
    client = FakeClient(
        {
            "orgs/ContextualWisdomLab/repos": [[repository()]],
            "repos/ContextualWisdomLab/example/pulls": [
                [
                    pull_list_item(number=i, updated_at="2026-08-05T11:00:00Z")
                    for i in range(1, 101)
                ],
                [pull_list_item(number=101, updated_at="2026-08-05T11:00:00Z")],
                [],
            ],
        }
    )

    def request(args, *, input_payload=None):
        if "repos/ContextualWisdomLab/example/pulls" in args[0]:
            page = int(
                next(arg for arg in args if arg.startswith("page=")).split("=")[1]
            )
            return client.responses["repos/ContextualWisdomLab/example/pulls"][page - 1]
        return client.responses.get(args[0])

    client.request = request

    pulls = list(
        sweep.list_recent_pull_requests(
            client,
            organization="ContextualWisdomLab",
            repository_source="organization",
            since="2026-08-05T10:00:00Z",
        )
    )
    assert len(pulls) == 101
