"""Review-driven pagination and failure-isolation regressions."""

from __future__ import annotations

import importlib
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts" / "ci"
sys.path.insert(0, str(SCRIPTS))


def module():
    """Reload the sweep module for isolated monkeypatching."""

    return importlib.reload(importlib.import_module("agent_mention_sweep"))


def repository(name: str) -> dict:
    """Build one active organization repository record."""

    return {
        "full_name": f"ContextualWisdomLab/{name}",
        "owner": {"login": "ContextualWisdomLab"},
        "archived": False,
        "disabled": False,
    }


class PagingClient:
    """Serve page-aware endpoint responses and deterministic failures."""

    def __init__(self, responses) -> None:
        """Initialize an endpoint/page response map."""

        self.responses = responses
        self.calls: list[list[str]] = []

    def request(self, args, *, input_payload=None):
        """Return one endpoint/page response or raise its configured error."""

        del input_payload
        args = list(args)
        self.calls.append(args)
        endpoint = args[0]
        page = 1
        for index, value in enumerate(args[:-1]):
            if value == "-f" and args[index + 1].startswith("page="):
                page = int(args[index + 1].split("=", 1)[1])
        response = self.responses[(endpoint, page)]
        if isinstance(response, Exception):
            raise response
        return response


def pull(number: int, updated_at: str = "2026-08-06T11:00:00Z") -> dict:
    """Build one pull-list response record."""

    return {"number": number, "updated_at": updated_at}


def test_pull_pagination_stops_at_cutoff_without_loading_later_pages() -> None:
    """Updated-descending pages stop immediately at the first old record."""

    sweep = module()
    recent = [pull(number) for number in range(1, 101)]
    client = PagingClient(
        {
            ("orgs/ContextualWisdomLab/repos", 1): [[repository("example")]],
            ("repos/ContextualWisdomLab/example/pulls", 1): recent,
            ("repos/ContextualWisdomLab/example/pulls", 2): [
                pull(101, "2026-08-01T00:00:00Z")
            ],
        }
    )
    results = list(
        sweep.list_recent_pull_requests(
            client,
            organization="ContextualWisdomLab",
            repository_source="organization",
            since="2026-08-05T00:00:00Z",
        )
    )
    assert len(results) == 100
    pull_calls = [
        args for args in client.calls if args[0].endswith("/pulls")
    ]
    assert len(pull_calls) == 2
    assert not any("page=3" in args for args in pull_calls)
    assert sweep.flatten_pages([{"number": 1}]) == [{"number": 1}]


def test_pull_pagination_stops_on_empty_followup_page() -> None:
    """A full page followed by an empty page terminates without page three."""

    sweep = module()
    recent = [pull(number) for number in range(1, 101)]
    client = PagingClient(
        {
            ("orgs/ContextualWisdomLab/repos", 1): [[repository("example")]],
            ("repos/ContextualWisdomLab/example/pulls", 1): recent,
            ("repos/ContextualWisdomLab/example/pulls", 2): [],
        }
    )
    results = list(
        sweep.list_recent_pull_requests(
            client,
            organization="ContextualWisdomLab",
            repository_source="organization",
            since="2026-08-05T00:00:00Z",
        )
    )
    assert len(results) == 100
    pull_calls = [
        args for args in client.calls if args[0].endswith("/pulls")
    ]
    assert len(pull_calls) == 2
    assert any("page=2" in args for args in pull_calls)
    assert not any("page=3" in args for args in pull_calls)


def test_invalid_pull_number_fails_closed_without_error_sink() -> None:
    """Malformed pull metadata raises when no isolation sink is supplied."""

    sweep = module()
    client = PagingClient(
        {
            ("orgs/ContextualWisdomLab/repos", 1): [[repository("example")]],
            ("repos/ContextualWisdomLab/example/pulls", 1): [pull(0)],
        }
    )
    with pytest.raises(ValueError, match="invalid pull request number"):
        list(
            sweep.list_recent_pull_requests(
                client,
                organization="ContextualWisdomLab",
                repository_source="organization",
                since="2026-08-05T00:00:00Z",
            )
        )


def test_repository_failure_is_isolated_and_later_repository_runs() -> None:
    """A repository-local API failure does not terminate organization traversal."""

    sweep = module()
    client = PagingClient(
        {
            ("orgs/ContextualWisdomLab/repos", 1): [[
                repository("broken"),
                repository("healthy"),
            ]],
            ("repos/ContextualWisdomLab/broken/pulls", 1): RuntimeError(
                "forbidden"
            ),
            ("repos/ContextualWisdomLab/healthy/pulls", 1): [pull(7)],
        }
    )
    failures = []
    results = list(
        sweep.list_recent_pull_requests(
            client,
            organization="ContextualWisdomLab",
            repository_source="organization",
            since="2026-08-05T00:00:00Z",
            on_error=lambda scope, error: failures.append(
                (scope, str(error))
            ),
        )
    )
    assert [result["repository"] for result in results] == [
        "ContextualWisdomLab/healthy"
    ]
    assert failures == [("ContextualWisdomLab/broken", "forbidden")]


def test_fetch_repo_pulls_stops_after_cancellation_during_page_request() -> None:
    """Cancellation observed after a request prevents all later page work."""

    sweep = module()
    cancelled = threading.Event()

    class CancellingClient(PagingClient):
        """Set the shared cancellation signal as page one returns."""

        def request(self, args, *, input_payload=None):
            """Return one page and cancel before the caller processes it."""

            response = super().request(args, input_payload=input_payload)
            cancelled.set()
            return response

    client = CancellingClient(
        {
            ("repos/ContextualWisdomLab/example/pulls", 1): [
                pull(number) for number in range(1, 101)
            ],
            ("repos/ContextualWisdomLab/example/pulls", 2): [pull(101)],
        }
    )

    assert sweep._fetch_repo_pulls(
        client,
        "ContextualWisdomLab/example",
        datetime(2026, 8, 5, tzinfo=timezone.utc),
        cancelled,
    ) == []
    assert len(client.calls) == 1


def test_fetch_repo_pulls_skips_requests_when_already_cancelled() -> None:
    """A pre-cancelled worker returns before materializing an API request."""

    sweep = module()
    cancelled = threading.Event()
    cancelled.set()
    client = PagingClient({})

    assert sweep._fetch_repo_pulls(
        client,
        "ContextualWisdomLab/example",
        datetime(2026, 8, 5, tzinfo=timezone.utc),
        cancelled,
    ) == []
    assert client.calls == []


def test_recent_pull_results_preserve_repository_order(monkeypatch) -> None:
    """Concurrent fetch completion cannot change bounded sweep selection order."""

    sweep = module()
    fast_finished = threading.Event()
    monkeypatch.setattr(
        sweep,
        "list_accessible_repositories",
        lambda *args, **kwargs: [
            "ContextualWisdomLab/slow-first",
            "ContextualWisdomLab/fast-second",
        ],
    )

    def fetch(client, repository_name, cutoff, cancelled):
        """Finish the second repository first while retaining source order."""

        del client, cutoff, cancelled
        if repository_name.endswith("/slow-first"):
            assert fast_finished.wait(1)
        else:
            fast_finished.set()
        return [{"repository": repository_name, "number": 7}]

    monkeypatch.setattr(sweep, "_fetch_repo_pulls", fetch)
    results = list(
        sweep.list_recent_pull_requests(
            object(),
            organization="ContextualWisdomLab",
            repository_source="organization",
            since="2026-08-05T00:00:00Z",
        )
    )

    assert [result["repository"] for result in results] == [
        "ContextualWisdomLab/slow-first",
        "ContextualWisdomLab/fast-second",
    ]


def test_single_repository_uses_serial_fast_path(monkeypatch) -> None:
    """A one-repository sweep avoids executor lifecycle and thread overhead."""

    sweep = module()
    monkeypatch.setattr(
        sweep,
        "list_accessible_repositories",
        lambda *args, **kwargs: ["ContextualWisdomLab/only"],
    )
    monkeypatch.setattr(
        sweep.concurrent.futures,
        "ThreadPoolExecutor",
        lambda *args, **kwargs: pytest.fail("single repository created an executor"),
    )
    monkeypatch.setattr(
        sweep,
        "_fetch_repo_pulls",
        lambda *args, **kwargs: [
            {"repository": "ContextualWisdomLab/only", "number": 7}
        ],
    )

    assert list(
        sweep.list_recent_pull_requests(
            object(),
            organization="ContextualWisdomLab",
            repository_source="organization",
            since="2026-08-05T00:00:00Z",
        )
    ) == [{"repository": "ContextualWisdomLab/only", "number": 7}]


def test_single_repository_failure_uses_isolation_sink(monkeypatch) -> None:
    """The serial fast path preserves repository-local error isolation."""

    sweep = module()
    monkeypatch.setattr(
        sweep,
        "list_accessible_repositories",
        lambda *args, **kwargs: ["ContextualWisdomLab/only"],
    )
    monkeypatch.setattr(
        sweep,
        "_fetch_repo_pulls",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("forbidden")),
    )
    failures = []

    assert list(
        sweep.list_recent_pull_requests(
            object(),
            organization="ContextualWisdomLab",
            repository_source="organization",
            since="2026-08-05T00:00:00Z",
            on_error=lambda scope, error: failures.append((scope, str(error))),
        )
    ) == []
    assert failures == [("ContextualWisdomLab/only", "forbidden")]


def test_parallel_repository_failure_raises_without_sink(monkeypatch) -> None:
    """Concurrent collection fails closed when no isolation sink is supplied."""

    sweep = module()
    monkeypatch.setattr(
        sweep,
        "list_accessible_repositories",
        lambda *args, **kwargs: [
            "ContextualWisdomLab/broken",
            "ContextualWisdomLab/healthy",
        ],
    )

    def fetch(client, repository_name, cutoff, cancelled):
        """Fail the first repository while allowing its peer to finish."""

        del client, cutoff, cancelled
        if repository_name.endswith("/broken"):
            raise RuntimeError("forbidden")
        return []

    monkeypatch.setattr(sweep, "_fetch_repo_pulls", fetch)
    with pytest.raises(RuntimeError, match="forbidden"):
        list(
            sweep.list_recent_pull_requests(
                object(),
                organization="ContextualWisdomLab",
                repository_source="organization",
                since="2026-08-05T00:00:00Z",
            )
        )


def test_closing_recent_pull_iterator_cancels_without_waiting(
    monkeypatch,
) -> None:
    """Closing the lazy stream signals workers and never joins blocked work."""

    sweep = module()
    slow_started = threading.Event()
    release_slow = threading.Event()
    observed_signals = []

    monkeypatch.setattr(
        sweep,
        "list_accessible_repositories",
        lambda *args, **kwargs: [
            "ContextualWisdomLab/fast",
            "ContextualWisdomLab/slow",
        ],
    )

    def fetch(client, repository_name, cutoff, cancelled):
        """Return one candidate while a peer worker remains blocked."""

        del client, cutoff
        observed_signals.append(cancelled)
        if repository_name.endswith("/slow"):
            slow_started.set()
            release_slow.wait(2)
            return []
        assert slow_started.wait(1)
        return [{"repository": repository_name, "number": 7}]

    monkeypatch.setattr(sweep, "_fetch_repo_pulls", fetch)
    iterator = sweep.list_recent_pull_requests(
        object(),
        organization="ContextualWisdomLab",
        repository_source="organization",
        since="2026-08-05T00:00:00Z",
    )
    try:
        assert next(iterator)["repository"].endswith("/fast")
        started = time.monotonic()
        iterator.close()
        assert time.monotonic() - started < 0.25
        assert len(observed_signals) == 2
        assert observed_signals[0] is observed_signals[1]
        assert observed_signals[0].is_set()
    finally:
        release_slow.set()


def mention_request(comment_id: int):
    """Build one Noema request for orchestration isolation tests."""

    router = importlib.import_module("agent_mention_router")
    return router.MentionRequest(
        "ContextualWisdomLab/example",
        7,
        "a" * 40,
        "main",
        comment_id,
        "maintainer",
        ("cwl-noema-review",),
    )


def test_sweep_continues_after_candidate_and_dispatch_failures(
    monkeypatch,
    capsys,
) -> None:
    """Candidate-local failures are counted while later work is queued."""

    sweep = module()
    issues = [
        {"repository": "ContextualWisdomLab/example", "number": 7},
        {"repository": "ContextualWisdomLab/example", "number": 8},
    ]
    monkeypatch.setattr(
        sweep,
        "list_recent_pull_requests",
        lambda *args, **kwargs: iter(issues),
    )

    def build_requests(client, *, issue, since):
        del client, since
        if issue["number"] == 7:
            raise RuntimeError("comment inventory failed")
        return (mention_request(10), mention_request(11))

    monkeypatch.setattr(sweep, "build_requests_for_pull_request", build_requests)
    dispatch_kwargs = []

    def dispatch(request, **kwargs):
        dispatch_kwargs.append(kwargs)
        if request.comment_id == 10:
            raise RuntimeError("dispatch failed")
        return ("@cwl-noema-review",)

    monkeypatch.setattr(sweep, "dispatch_request", dispatch)
    metrics = sweep.SweepMetrics()
    assert sweep.sweep(
        target_client=object(),
        dispatch_client=object(),
        organization="ContextualWisdomLab",
        repository_source="organization",
        lookback_hours=24,
        max_dispatches=5,
        opencode_allowlist=frozenset(),
        now=datetime(2026, 8, 6, tzinfo=timezone.utc),
        metrics=metrics,
    ) == 1
    assert metrics.failures == 2
    assert dispatch_kwargs[0]["ledger_artifact_cache"] is dispatch_kwargs[1][
        "ledger_artifact_cache"
    ]
    assert dispatch_kwargs[0]["dry_run"] is False
    output = capsys.readouterr().out
    assert "comment inventory failed" in output
    assert "dispatch failed" in output


def test_dispatch_limit_explicitly_closes_candidate_stream(monkeypatch) -> None:
    """The bounded dispatch exit explicitly closes its concurrent source."""

    sweep = module()

    class CandidateStream:
        """Expose whether the scheduler explicitly closed its source."""

        def __init__(self) -> None:
            """Initialize one candidate and an open state."""

            self.remaining = iter([
                {"repository": "ContextualWisdomLab/example", "number": 7}
            ])
            self.closed = False

        def __iter__(self):
            """Return this candidate iterator."""

            return self

        def __next__(self):
            """Return the next candidate."""

            return next(self.remaining)

        def close(self) -> None:
            """Record explicit source shutdown."""

            self.closed = True

    candidates = CandidateStream()
    monkeypatch.setattr(
        sweep,
        "list_recent_pull_requests",
        lambda *args, **kwargs: candidates,
    )
    monkeypatch.setattr(
        sweep,
        "build_requests_for_pull_request",
        lambda *args, **kwargs: (mention_request(12),),
    )
    monkeypatch.setattr(
        sweep,
        "dispatch_request",
        lambda *args, **kwargs: ("@cwl-noema-review",),
    )

    assert sweep.sweep(
        target_client=object(),
        dispatch_client=object(),
        organization="ContextualWisdomLab",
        repository_source="organization",
        lookback_hours=24,
        max_dispatches=1,
        opencode_allowlist=frozenset(),
        now=datetime(2026, 8, 6, tzinfo=timezone.utc),
    ) == 1
    assert candidates.closed is True


def test_main_returns_failure_when_isolated_errors_were_observed(
    monkeypatch,
) -> None:
    """The scheduled workflow remains visibly failed after partial progress."""

    sweep = module()
    monkeypatch.setenv("TARGET_REPOSITORY_TOKEN", "target")
    monkeypatch.setenv("AGENT_DISPATCH_TOKEN", "dispatch")

    def fail_partially(**kwargs):
        kwargs["metrics"].failures = 1
        return 0

    monkeypatch.setattr(sweep, "sweep", fail_partially)
    assert sweep.main([]) == 1
