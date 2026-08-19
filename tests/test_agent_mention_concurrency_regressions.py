"""Concurrency and transport regressions for the agent-mention sweep."""

from __future__ import annotations

import importlib
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts" / "ci"
sys.path.insert(0, str(SCRIPTS))


def router_module():
    """Reload the router module for isolated subprocess monkeypatching."""

    return importlib.reload(importlib.import_module("agent_mention_router"))


def sweep_module():
    """Reload the sweep module for isolated executor tests."""

    return importlib.reload(importlib.import_module("agent_mention_sweep"))


def repository(name: str) -> dict:
    """Build one active organization repository record."""

    return {
        "full_name": f"ContextualWisdomLab/{name}",
        "owner": {"login": "ContextualWisdomLab"},
        "archived": False,
        "disabled": False,
    }


def pull(number: int, updated_at: str = "2026-08-06T11:00:00Z") -> dict:
    """Build one pull-list response record."""

    return {"number": number, "updated_at": updated_at}


class PagingClient:
    """Serve endpoint/page responses and record request order."""

    def __init__(self, responses) -> None:
        """Initialize an endpoint/page response map."""

        self.responses = responses
        self.calls: list[list[str]] = []

    def request(self, args, *, input_payload=None):
        """Return a configured page or raise its configured exception."""

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


def test_github_client_request_is_timeout_bounded(monkeypatch) -> None:
    """Every gh subprocess has a finite timeout with an explicit diagnostic."""

    router = router_module()

    def time_out(command, **kwargs):
        timeout = kwargs.get("timeout")
        assert timeout == 60
        raise router.subprocess.TimeoutExpired(command, timeout)

    monkeypatch.setattr(router.subprocess, "run", time_out)

    with pytest.raises(RuntimeError, match="timed out after 60 seconds"):
        router.GitHubClient("token").request(["repos/x/y"])


def test_rate_limit_failure_is_one_bounded_request(monkeypatch) -> None:
    """Rate-limit diagnostics remain isolated without automatic retry amplification."""

    router = router_module()
    calls = []

    def rate_limited(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(
            stdout="",
            stderr="API rate limit exceeded\n",
            returncode=1,
        )

    monkeypatch.setattr(router.subprocess, "run", rate_limited)

    with pytest.raises(RuntimeError, match="API rate limit exceeded"):
        router.GitHubClient("token").request(["repos/x/y"])

    assert len(calls) == 1
    assert calls[0][1]["timeout"] == 60


def test_repository_error_sink_runs_on_generator_thread() -> None:
    """Repository failures mutate caller-owned metrics only on the consumer thread."""

    sweep = sweep_module()
    caller_thread = threading.get_ident()
    failures = []
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

    results = list(
        sweep.list_recent_pull_requests(
            client,
            organization="ContextualWisdomLab",
            repository_source="organization",
            since="2026-08-05T00:00:00Z",
            on_error=lambda scope, error: failures.append(
                (threading.get_ident(), scope, str(error))
            ),
        )
    )

    assert [result["repository"] for result in results] == [
        "ContextualWisdomLab/healthy"
    ]
    assert failures == [
        (caller_thread, "ContextualWisdomLab/broken", "forbidden")
    ]


def test_pull_pagination_still_stops_at_cutoff() -> None:
    """Concurrent repository fetching preserves cutoff-aware page traversal."""

    sweep = sweep_module()
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
    pull_calls = [args for args in client.calls if args[0].endswith("/pulls")]
    assert len(pull_calls) == 2
    assert any("page=2" in args for args in pull_calls)
    assert not any("page=3" in args for args in pull_calls)


def test_generator_close_does_not_wait_for_running_repository() -> None:
    """Early consumer exit keeps non-waiting executor shutdown semantics."""

    sweep = sweep_module()
    slow_started = threading.Event()
    release_slow = threading.Event()

    class EarlyCloseClient:
        """Return one fast result while keeping another request in progress."""

        def request(self, args, *, input_payload=None):
            del input_payload
            endpoint = args[0]
            if endpoint == "orgs/ContextualWisdomLab/repos":
                return [[repository("fast"), repository("slow")]]
            if endpoint == "repos/ContextualWisdomLab/fast/pulls":
                return [pull(1)]
            if endpoint == "repos/ContextualWisdomLab/slow/pulls":
                slow_started.set()
                release_slow.wait(timeout=2)
                return [pull(2)]
            raise AssertionError(endpoint)

    generator = sweep.list_recent_pull_requests(
        EarlyCloseClient(),
        organization="ContextualWisdomLab",
        repository_source="organization",
        since="2026-08-05T00:00:00Z",
    )
    assert next(generator)["repository"] == "ContextualWisdomLab/fast"
    assert slow_started.wait(timeout=1)

    started = time.monotonic()
    generator.close()
    elapsed = time.monotonic() - started
    release_slow.set()

    assert elapsed < 0.5


def test_repository_failure_without_sink_still_fails_closed() -> None:
    """Moving error handling does not convert unhandled failures into success."""

    sweep = sweep_module()
    client = PagingClient(
        {
            ("orgs/ContextualWisdomLab/repos", 1): [[repository("broken")]],
            ("repos/ContextualWisdomLab/broken/pulls", 1): RuntimeError(
                "forbidden"
            ),
        }
    )

    with pytest.raises(RuntimeError, match="forbidden"):
        list(
            sweep.list_recent_pull_requests(
                client,
                organization="ContextualWisdomLab",
                repository_source="organization",
                since="2026-08-05T00:00:00Z",
            )
        )
