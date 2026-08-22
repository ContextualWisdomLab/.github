"""Bounded GitHub subprocess and repository-fanout regression tests."""

from __future__ import annotations

import importlib
import subprocess
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts" / "ci"
sys.path.insert(0, str(SCRIPTS))


def router_module():
    """Reload the central mention router for isolated monkeypatching."""

    return importlib.reload(importlib.import_module("agent_mention_router"))


def sweep_module():
    """Reload the organization sweep for isolated monkeypatching."""

    router_module()
    return importlib.reload(importlib.import_module("agent_mention_sweep"))


def repository(name: str) -> dict:
    """Return one active repository record."""

    return {
        "full_name": f"ContextualWisdomLab/{name}",
        "owner": {"login": "ContextualWisdomLab"},
        "archived": False,
        "disabled": False,
    }


def pull(number: int) -> dict:
    """Return one recent pull-request list record."""

    return {"number": number, "updated_at": "2026-08-20T00:00:00Z"}


class InventoryClient:
    """Serve a deterministic repository inventory and one pull per repository."""

    def __init__(self, names: tuple[str, ...]) -> None:
        """Store the repository names exposed to the sweep."""

        self.names = names

    def request(self, args, *, input_payload=None):
        """Return the organization inventory or one repository pull list."""

        del input_payload
        endpoint = args[0]
        if endpoint == "orgs/ContextualWisdomLab/repos":
            return [repository(name) for name in self.names]
        name = endpoint.split("/")[2]
        return [pull(self.names.index(name) + 1)]


def test_github_client_applies_one_finite_timeout(monkeypatch) -> None:
    """Every ``gh api`` subprocess receives the reviewed timeout bound."""

    router = router_module()
    observed = []

    def fake_run(command, **kwargs):
        """Return a successful JSON response while recording subprocess options."""
        observed.append((command, kwargs))
        return SimpleNamespace(stdout='{"ok": true}\n', returncode=0)

    monkeypatch.setattr(router.subprocess, "run", fake_run)
    result = router.GitHubClient("token").request(["repos/x/y"])

    assert result == {"ok": True}
    assert observed[0][1]["timeout"] == router.GITHUB_API_TIMEOUT_SECONDS == 30


def test_github_client_converts_timeout_to_bounded_diagnostic(monkeypatch) -> None:
    """A hung CLI request fails visibly without leaking token or payload data."""

    router = router_module()

    def timeout_run(command, **kwargs):
        """Raise the same timeout the production wrapper must translate."""
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(router.subprocess, "run", timeout_run)
    with pytest.raises(RuntimeError, match="gh api timed out after 30 seconds"):
        router.GitHubClient("secret-token").request(
            ["repos/x/y"],
            input_payload={"sensitive": "value"},
        )


def test_github_client_retries_a_completed_failure_with_backoff(monkeypatch) -> None:
    """A transient rate limit succeeds after retrying with linear backoff."""

    router = router_module()
    attempts = []
    sleeps = []

    def flaky_run(command, **kwargs):
        """Fail with a rate-limit diagnostic twice, then succeed."""
        del kwargs
        attempts.append(command)
        if len(attempts) < 3:
            return SimpleNamespace(
                stdout="",
                stderr="gh: API rate limit exceeded for installation ID 1",
                returncode=1,
            )
        return SimpleNamespace(stdout='{"ok": true}\n', returncode=0)

    monkeypatch.setattr(router.subprocess, "run", flaky_run)
    monkeypatch.setattr(router.time, "sleep", lambda seconds: sleeps.append(seconds))
    result = router.GitHubClient("token").request(["repos/x/y"])

    assert result == {"ok": True}
    assert len(attempts) == 3
    assert sleeps == [5, 10]


def test_github_client_fails_closed_after_exhausting_retries(monkeypatch) -> None:
    """A persistent rate limit still fails after all retries, not silently."""

    router = router_module()
    attempts = []
    sleeps = []

    def always_fails(command, **kwargs):
        """Fail every attempt with a stable rate-limit diagnostic."""
        del kwargs
        attempts.append(command)
        return SimpleNamespace(
            stdout="",
            stderr="gh: API rate limit exceeded for installation ID 1",
            returncode=1,
        )

    monkeypatch.setattr(router.subprocess, "run", always_fails)
    monkeypatch.setattr(router.time, "sleep", lambda seconds: sleeps.append(seconds))
    with pytest.raises(
        RuntimeError,
        match=r"gh api failed with exit code 1 after 6 attempts: "
        r"gh: API rate limit exceeded",
    ):
        router.GitHubClient("token").request(["repos/x/y"])

    assert len(attempts) == router.GITHUB_API_MAX_ATTEMPTS == 6
    assert sleeps == [5, 10, 15, 20, 25]


def test_github_client_does_not_retry_a_non_rate_limit_failure(monkeypatch) -> None:
    """A permanent failure (e.g. 404, permission denied) fails on the first attempt.

    Retrying an unknown failure could resend a non-idempotent write (a
    ``repository_dispatch`` POST or an acknowledgement comment) that may
    have already applied server-side; only the specific, safe-to-retry
    rate-limit diagnostic is retried.
    """

    router = router_module()
    attempts = []
    sleeps = []

    def permission_denied(command, **kwargs):
        """Fail once with a diagnostic that is not a rate limit."""
        del kwargs
        attempts.append(command)
        return SimpleNamespace(stdout="", stderr="permission denied", returncode=1)

    monkeypatch.setattr(router.subprocess, "run", permission_denied)
    monkeypatch.setattr(router.time, "sleep", lambda seconds: sleeps.append(seconds))
    with pytest.raises(
        RuntimeError,
        match=r"gh api failed with exit code 1: permission denied",
    ):
        router.GitHubClient("token").request(["repos/x/y"])

    assert len(attempts) == 1
    assert sleeps == []


def test_repository_fanout_uses_exactly_four_workers_at_scale(monkeypatch) -> None:
    """Five repositories exercise the fixed four-worker production ceiling."""

    sweep = sweep_module()
    names = ("alpha", "bravo", "charlie", "delta", "echo")
    real_executor = sweep.concurrent.futures.ThreadPoolExecutor
    worker_limits = []

    def recording_executor(*, max_workers):
        """Record the configured worker ceiling before creating real workers."""
        worker_limits.append(max_workers)
        return real_executor(max_workers=max_workers)

    monkeypatch.setattr(
        sweep.concurrent.futures,
        "ThreadPoolExecutor",
        recording_executor,
    )
    results = list(
        sweep.list_recent_pull_requests(
            InventoryClient(names),
            organization="ContextualWisdomLab",
            repository_source="organization",
            since="2026-08-19T00:00:00Z",
        )
    )

    assert worker_limits == [4]
    assert sorted(item["repository"] for item in results) == sorted(
        f"ContextualWisdomLab/{name}" for name in names
    )


def test_repository_fanout_yields_fast_repository_before_slow_one() -> None:
    """A slow first repository must not hide a completed later repository."""

    sweep = sweep_module()
    slow_started = threading.Event()
    fast_finished = threading.Event()
    release_slow = threading.Event()
    first_yielded = threading.Event()

    class FairnessClient:
        """Block one repository while allowing the next one to complete."""

        def request(self, args, *, input_payload=None):
            """Return the inventory or one deliberately paced pull list."""

            del input_payload
            endpoint = args[0]
            if endpoint == "orgs/ContextualWisdomLab/repos":
                return [repository("alpha"), repository("bravo")]
            if endpoint.endswith("alpha/pulls"):
                slow_started.set()
                assert release_slow.wait(2)
                return [pull(1)]
            if endpoint.endswith("bravo/pulls"):
                fast_finished.set()
                return [pull(2)]
            raise AssertionError(f"unexpected endpoint: {endpoint}")

    generator = sweep.list_recent_pull_requests(
        FairnessClient(),
        organization="ContextualWisdomLab",
        repository_source="organization",
        since="2026-08-19T00:00:00Z",
    )
    first_result = []

    def read_first_result() -> None:
        """Read one result without blocking the test's release signal."""

        first_result.append(next(generator))
        first_yielded.set()

    reader = threading.Thread(target=read_first_result)
    reader.start()
    assert slow_started.wait(2)
    assert fast_finished.wait(2)
    yielded_before_slow_release = first_yielded.wait(0.5)
    release_slow.set()
    reader.join(2)
    assert not reader.is_alive()
    assert yielded_before_slow_release
    assert first_result[0]["repository"] == "ContextualWisdomLab/bravo"
    assert {item["repository"] for item in generator} == {
        "ContextualWisdomLab/alpha"
    }


def test_empty_inventory_does_not_construct_an_executor(monkeypatch) -> None:
    """The zero-repository fast path never allocates worker threads."""

    sweep = sweep_module()

    def forbidden_executor(*args, **kwargs):
        """Fail the test if the empty inventory allocates an executor."""
        raise AssertionError(f"executor called with {args!r} {kwargs!r}")

    monkeypatch.setattr(
        sweep.concurrent.futures,
        "ThreadPoolExecutor",
        forbidden_executor,
    )
    assert list(
        sweep.list_recent_pull_requests(
            InventoryClient(()),
            organization="ContextualWisdomLab",
            repository_source="organization",
            since="2026-08-19T00:00:00Z",
        )
    ) == []


def test_generator_close_stops_additional_pages_after_inflight_request(
    monkeypatch,
) -> None:
    """Closing after the dispatch frontier bounds a running repository fetch."""

    sweep = sweep_module()
    page_two_started = threading.Event()
    release_page_two = threading.Event()
    shutdown_started = threading.Event()

    class ClosingClient:
        """Keep the second repository in one bounded in-flight request."""

        def request(self, args, *, input_payload=None):
            """Return page one or pause page two until the closer releases it."""
            del input_payload
            endpoint = args[0]
            if endpoint == "orgs/ContextualWisdomLab/repos":
                return [repository("alpha"), repository("bravo")]
            page = 1
            for index, value in enumerate(args[:-1]):
                if value == "-f" and args[index + 1].startswith("page="):
                    page = int(args[index + 1].split("=", 1)[1])
            if endpoint.endswith("alpha/pulls"):
                return [pull(1)]
            if page == 1:
                return [pull(number) for number in range(100, 200)]
            if page == 2:
                page_two_started.set()
                assert release_page_two.wait(2)
                return [pull(number) for number in range(200, 300)]
            raise AssertionError(f"unexpected third page request: {args!r}")

    real_executor = sweep.concurrent.futures.ThreadPoolExecutor

    class RecordingExecutor:
        """Expose the moment shutdown begins while delegating real workers."""

        def __init__(self, *, max_workers):
            """Create the real bounded executor used by this test double."""
            self._inner = real_executor(max_workers=max_workers)

        def submit(self, *args, **kwargs):
            """Forward one repository fetch to the delegated executor."""
            return self._inner.submit(*args, **kwargs)

        def shutdown(self, *, wait, cancel_futures):
            """Record shutdown before forwarding the bounded cancellation call."""
            shutdown_started.set()
            return self._inner.shutdown(
                wait=wait,
                cancel_futures=cancel_futures,
            )

    monkeypatch.setattr(
        sweep.concurrent.futures,
        "ThreadPoolExecutor",
        RecordingExecutor,
    )
    generator = sweep.list_recent_pull_requests(
        ClosingClient(),
        organization="ContextualWisdomLab",
        repository_source="organization",
        since="2026-08-19T00:00:00Z",
    )
    assert next(generator)["repository"] == "ContextualWisdomLab/alpha"
    assert page_two_started.wait(2)

    closer = threading.Thread(target=generator.close)
    closer.start()
    assert shutdown_started.wait(2)
    release_page_two.set()
    closer.join(2)

    assert not closer.is_alive()
