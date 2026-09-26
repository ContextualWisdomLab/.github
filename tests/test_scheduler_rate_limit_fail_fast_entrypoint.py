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


def _post_approval_arguments() -> list[str]:
    """Return the exact OpenCode post-publication scheduler signature."""

    return [
        "--repo",
        "ContextualWisdomLab/example-service",
        "--base-branch",
        "main",
        "--max-prs",
        "1",
        "--project-flow",
        "github-flow",
        "--review-workflow",
        "Required OpenCode Review",
        "--security-workflow",
        "Strix Security Scan",
        "--review-dispatch-limit",
        "0",
        "--no-trigger-reviews",
        "--enable-auto-merge",
        "--merge-mode",
        "direct_or_auto",
        "--no-update-branches",
        "--pr-number",
        "42",
    ]


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


def test_graphql_transient_transport_error_keeps_one_short_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Preserve bounded recovery for a passing GraphQL transport failure."""

    responses: list[object] = [
        RuntimeError("HTTP 502: bad gateway"),
        '{"data": {"ok": true}}',
    ]
    sleeps: list[int] = []

    def transient_read(
        command: list[str], *, stdin: str | None = None
    ) -> str:
        assert stdin == "query { viewer { login } }"
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(scheduler_core, "run_github_read", transient_read)
    monkeypatch.setattr(scheduler_core.time, "sleep", sleeps.append)
    scheduler_facade.install_fail_fast_rate_limit_policy()

    assert scheduler_core.gh_graphql("query { viewer { login } }") == {
        "data": {"ok": True}
    }
    assert sleeps == [1]
    assert responses == []


def test_graphql_forwards_extra_fields_with_correct_flags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Forward string and integer GraphQL variables with their matching gh flags."""

    calls: list[list[str]] = []

    def capturing_read(
        command: list[str], *, stdin: str | None = None
    ) -> str:
        calls.append(command)
        return '{"data": {}}'

    monkeypatch.setattr(scheduler_core, "run_github_read", capturing_read)
    scheduler_facade.install_fail_fast_rate_limit_policy()

    scheduler_core.gh_graphql(
        "query($repo: String!, $number: Int!) { }",
        repo="ContextualWisdomLab/example-service",
        number=42,
    )

    assert calls == [
        [
            "gh",
            "api",
            "graphql",
            "-F",
            "query=@-",
            "-f",
            "repo=ContextualWisdomLab/example-service",
            "-F",
            "number=42",
        ]
    ]


def test_non_transient_graphql_and_rest_errors_raise_on_first_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Never retry a GitHub failure that is neither rate-limited nor transient."""

    calls: list[list[str]] = []
    sleeps: list[int] = []

    def failing_read(
        command: list[str], *, stdin: str | None = None
    ) -> str:
        calls.append(command)
        raise RuntimeError("HTTP 422: schema validation failed")

    monkeypatch.setattr(scheduler_core, "run_github_read", failing_read)
    monkeypatch.setattr(scheduler_core.time, "sleep", sleeps.append)
    scheduler_facade.install_fail_fast_rate_limit_policy()

    with pytest.raises(RuntimeError, match="schema validation failed"):
        scheduler_core.gh_graphql("query { viewer { login } }")
    with pytest.raises(RuntimeError, match="schema validation failed"):
        scheduler_core.gh_api_json("repos/example/project")

    assert len(calls) == 2
    assert sleeps == []


def test_opencode_followup_defer_without_step_summary_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Skip writing a job summary when no GITHUB_STEP_SUMMARY path is set."""

    argument_values = _post_approval_arguments()

    def deferred_main(received_arguments: list[str]) -> int:
        assert received_arguments == argument_values
        raise RuntimeError("API rate limit exceeded for installation")

    monkeypatch.setattr(scheduler_core, "main", deferred_main)
    monkeypatch.setenv("GITHUB_WORKFLOW", "OpenCode Review Dispatch")
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)

    assert scheduler_facade.run_cli(argument_values) == 0


def test_post_approval_signature_requires_a_value_after_each_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A tracked option with no following value never satisfies the signature."""

    argument_values = [*_post_approval_arguments()[:16], "--merge-mode"]

    def deferred_main(received_arguments: list[str]) -> int:
        assert received_arguments == argument_values
        raise RuntimeError("API rate limit exceeded for installation")

    monkeypatch.setattr(scheduler_core, "main", deferred_main)
    monkeypatch.setenv("GITHUB_WORKFLOW", "OpenCode Review Dispatch")

    assert scheduler_facade.run_cli(argument_values) == 1


def test_facade_dunder_attribute_writes_use_the_real_module_protocol() -> None:
    """Dunder names are never forwarded to the core module, even for writes."""

    original_doc = scheduler_facade.__doc__
    try:
        setattr(scheduler_facade, "__doc__", "temporary")
        assert scheduler_facade.__dict__["__doc__"] == "temporary"
        delattr(scheduler_facade, "__doc__")
        assert "__doc__" not in scheduler_facade.__dict__
    finally:
        setattr(scheduler_facade, "__doc__", original_doc)

    assert scheduler_facade.__doc__ == original_doc


def test_dir_merges_facade_and_core_module_names() -> None:
    """dir() on the facade module exposes both its own and the core's names."""

    names = dir(scheduler_facade)

    assert "run_cli" in names
    assert "gh_graphql" in names


def test_opencode_followup_accepts_typed_rate_limit_defer_without_outer_retry(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Stop the OpenCode caller's 5, 10, and 15 second retry sleeps."""

    argument_values = _post_approval_arguments()
    summary_path = tmp_path / "step-summary.md"
    sleeps: list[int] = []

    def deferred_main(received_arguments: list[str]) -> int:
        assert received_arguments == argument_values
        raise RuntimeError("API rate limit exceeded for installation")

    monkeypatch.setattr(scheduler_core, "main", deferred_main)
    monkeypatch.setattr(scheduler_core.time, "sleep", sleeps.append)
    monkeypatch.setenv("GITHUB_WORKFLOW", "OpenCode Review Dispatch")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_path))

    assert scheduler_facade.run_cli(argument_values) == 0
    assert sleeps == []
    summary = summary_path.read_text(encoding="utf-8")
    assert "outcome: `deferred_rate_limit`" in summary
    assert "retry owner: Required PR Review Merge Scheduler heartbeat" in summary
    assert "runner-held sleep: 0 seconds" in summary


def test_org_sweep_rate_limit_remains_nonzero_and_stops_rotation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Preserve #1245's organization-rotation stop signal."""

    argument_values = [
        "--repo",
        "ContextualWisdomLab/example-service",
        "--base-branch",
        "main",
        "--max-prs",
        "8",
        "--review-dispatch-limit",
        "3",
    ]

    def deferred_main(received_arguments: list[str]) -> int:
        assert received_arguments == argument_values
        raise RuntimeError("API rate limit exceeded for installation")

    monkeypatch.setattr(scheduler_core, "main", deferred_main)
    monkeypatch.setenv("GITHUB_WORKFLOW", "Required PR Review Merge Scheduler")

    assert scheduler_facade.run_cli(argument_values) == 1


def test_caller_name_alone_cannot_relabel_org_scan_as_accepted_defer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Require the exact post-approval argument signature as well as workflow."""

    argument_values = ["--repo", "ContextualWisdomLab/example-service"]

    def deferred_main(received_arguments: list[str]) -> int:
        assert received_arguments == argument_values
        raise RuntimeError("API rate limit exceeded for installation")

    monkeypatch.setattr(scheduler_core, "main", deferred_main)
    monkeypatch.setenv("GITHUB_WORKFLOW", "OpenCode Review Dispatch")

    assert scheduler_facade.run_cli(argument_values) == 1


def test_cli_keeps_non_rate_limit_failure_blocking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Do not relabel an unrelated scheduler defect as accepted deferral."""

    argument_values = _post_approval_arguments()

    def failing_main(received_arguments: list[str]) -> int:
        assert received_arguments == argument_values
        raise RuntimeError("invalid repository payload")

    monkeypatch.setattr(scheduler_core, "main", failing_main)
    monkeypatch.setenv("GITHUB_WORKFLOW", "OpenCode Review Dispatch")

    assert scheduler_facade.run_cli(argument_values) == 1


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
    assert "scheduler_outcome=deferred_rate_limit" in facade_source
    assert "Required PR Review Merge Scheduler heartbeat" in facade_source
    assert 'GITHUB_WORKFLOW", "") == "OpenCode Review Dispatch"' in facade_source
    assert "__all__ = tuple(" in facade_source
