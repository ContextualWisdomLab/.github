"""Contracts for fail-fast GitHub primary rate-limit handling."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.ci import pr_review_merge_scheduler as scheduler_facade
from scripts.ci import pr_review_merge_scheduler_core as scheduler_core


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
FACADE_PATH = (
    REPOSITORY_ROOT / "scripts" / "ci" / "pr_review_merge_scheduler.py"
)
CORE_PATH = (
    REPOSITORY_ROOT
    / "scripts"
    / "ci"
    / "pr_review_merge_scheduler_core.py"
)


@pytest.fixture(autouse=True)
def restore_scheduler_api_helpers():
    """Restore core API helpers after each installer-focused regression test."""

    original_graphql = scheduler_core.gh_graphql
    original_rest = scheduler_core.gh_api_json
    yield
    scheduler_core.gh_graphql = original_graphql
    scheduler_core.gh_api_json = original_rest


def test_graphql_rate_limit_fails_after_one_request_without_sleep(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Do not hold a runner once the shared GraphQL bucket is exhausted."""

    calls: list[list[str]] = []
    sleeps: list[int] = []

    def exhausted_read(
        command: list[str], *, stdin: str | None = None
    ) -> str:
        calls.append(command)
        assert stdin == "query { viewer { login } }"
        raise RuntimeError("API rate limit exceeded for installation")

    monkeypatch.setattr(scheduler_core, "run_github_read", exhausted_read)
    monkeypatch.setattr(scheduler_core.time, "sleep", sleeps.append)
    scheduler_facade.install_fail_fast_rate_limit_policy()

    with pytest.raises(RuntimeError, match="API rate limit exceeded"):
        scheduler_core.gh_graphql("query { viewer { login } }")

    assert len(calls) == 1
    assert sleeps == []
    assert ["gh", "api", "rate_limit"] not in calls


def test_rest_rate_limit_fails_after_one_request_without_sleep(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Do not query reset metadata or sleep after a REST bucket exhaustion."""

    calls: list[list[str]] = []
    sleeps: list[int] = []

    def exhausted_read(
        command: list[str], *, stdin: str | None = None
    ) -> str:
        calls.append(command)
        assert stdin is None
        raise RuntimeError("API rate limit exceeded for installation")

    monkeypatch.setattr(scheduler_core, "run_github_read", exhausted_read)
    monkeypatch.setattr(scheduler_core.time, "sleep", sleeps.append)
    scheduler_facade.install_fail_fast_rate_limit_policy()

    with pytest.raises(RuntimeError, match="API rate limit exceeded"):
        scheduler_core.gh_api_json("repos/example/project")

    assert calls == [["gh", "api", "repos/example/project"]]
    assert sleeps == []


def test_transient_transport_error_keeps_one_short_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Preserve bounded recovery for a passing GitHub transport failure."""

    responses: list[object] = [
        RuntimeError("temporary server error"),
        '{"ok": true}',
    ]
    sleeps: list[int] = []

    def transient_read(
        command: list[str], *, stdin: str | None = None
    ) -> str:
        assert command == ["gh", "api", "repos/example/project"]
        assert stdin is None
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(scheduler_core, "run_github_read", transient_read)
    monkeypatch.setattr(scheduler_core.time, "sleep", sleeps.append)
    scheduler_facade.install_fail_fast_rate_limit_policy()

    assert scheduler_core.gh_api_json("repos/example/project") == {
        "ok": True
    }
    assert sleeps == [1]
    assert responses == []


def test_legacy_monkeypatches_are_forwarded_to_the_core_module(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep existing tests and callers on the stable import path."""

    sentinel = object()
    monkeypatch.setattr(
        scheduler_facade,
        "DEFAULT_STALE_OPENCODE_MINUTES",
        sentinel,
    )

    assert scheduler_core.DEFAULT_STALE_OPENCODE_MINUTES is sentinel
    assert scheduler_facade.DEFAULT_STALE_OPENCODE_MINUTES is sentinel


def test_wildcard_import_preserves_the_original_public_scheduler_api() -> None:
    """Export delegated public APIs through the stable facade path."""

    imported_namespace: dict[str, object] = {}
    exec(
        "from scripts.ci.pr_review_merge_scheduler import *",
        imported_namespace,
    )

    assert imported_namespace["main"] is scheduler_core.main
    assert imported_namespace["gh_graphql"] is scheduler_core.gh_graphql
    assert imported_namespace["gh_api_json"] is scheduler_core.gh_api_json
    assert "_scheduler_core" not in imported_namespace
    assert "main" in scheduler_facade.__all__


def test_core_owns_the_existing_dispatch_contract_markers() -> None:
    """Keep static dispatch evidence on the implementation, not only facade."""

    core_source = CORE_PATH.read_text(encoding="utf-8")
    for marker in (
        'f"repos/{dispatch_repo}/dispatches"',
        '"event_type": "opencode-review"',
        '"event_type": "strix-scan"',
    ):
        assert marker in core_source


def test_facade_installs_no_reset_lookup_on_the_production_entrypoint() -> None:
    """Guard against reintroducing rate-limit polling into the stable CLI."""

    facade_source = FACADE_PATH.read_text(encoding="utf-8")

    assert "install_fail_fast_rate_limit_policy()" in facade_source
    assert "rate_limit_retry_delay_seconds(" not in facade_source
    assert '["gh", "api", "rate_limit"]' not in facade_source
    assert "deferring without runner-held sleep" in facade_source
    assert "__all__ = tuple(" in facade_source
