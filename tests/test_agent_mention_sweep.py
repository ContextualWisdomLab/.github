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


def test_sweep_isolates_a_failed_repository_listing(monkeypatch, capsys) -> None:
    """An exception from the initial repository listing does not crash the sweep.

    list_accessible_repositories runs once, synchronously, before
    list_recent_pull_requests' first yield, and has no on_error boundary of
    its own — unlike every per-repository fetch inside the executor. A
    rate-limit exhaustion there must be treated as one isolated failure
    (record_failure + a clean return), not an uncaught crash that wastes
    the whole cycle.
    """

    sweep = module()

    def raise_on_listing(*args, **kwargs):
        """Raise as if the organization repository listing exhausted retries."""

        del args, kwargs
        raise RuntimeError(
            "gh api failed with exit code 1 after 6 attempts: "
            "gh: API rate limit exceeded for installation ID 1"
        )
        yield  # pragma: no cover - makes this a generator function

    monkeypatch.setattr(sweep, "list_recent_pull_requests", raise_on_listing)
    result = sweep.sweep(
        target_client=FakeClient(),
        dispatch_client=FakeClient(),
        organization="ContextualWisdomLab",
        repository_source="organization",
        lookback_hours=24,
        max_dispatches=1,
        opencode_allowlist=frozenset(),
        now=datetime(2026, 8, 5, tzinfo=timezone.utc),
    )

    assert result == 0
    output = capsys.readouterr().out
    assert "ContextualWisdomLab repository listing" in output
    assert "rate limit exceeded" in output


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


def test_sweep_redacts_credentials_from_isolated_failure_messages(
    monkeypatch, capsys
) -> None:
    """An exception message that embeds a credential is redacted before logging.

    An isolated request/PR failure can wrap the underlying gh api stderr
    verbatim (e.g. a malformed URL or verbose HTTP dump that happens to
    include a token). record_failure must not leak that text into the
    job's public log output.
    """

    sweep = module()
    leaked_token = "ghp_" + ("A" * 24)
    monkeypatch.setattr(
        sweep, "list_recent_pull_requests", lambda *args, **kwargs: iter([candidate()])
    )

    def raise_with_token(*args, **kwargs):
        """Raise an error whose message embeds a credential-shaped token."""

        del args, kwargs
        raise RuntimeError(f"gh api failed: Authorization: Bearer {leaked_token}")

    monkeypatch.setattr(
        sweep, "build_requests_for_pull_request", raise_with_token
    )
    result = sweep.sweep(
        target_client=FakeClient(),
        dispatch_client=FakeClient(),
        organization="ContextualWisdomLab",
        repository_source="organization",
        lookback_hours=24,
        max_dispatches=1,
        opencode_allowlist=frozenset(),
        now=datetime(2026, 8, 5, tzinfo=timezone.utc),
    )

    assert result == 0
    output = capsys.readouterr().out
    assert leaked_token not in output
    assert "Agent mention sweep skipped" in output


def test_sweep_stops_before_its_time_budget_to_exit_cleanly(
    monkeypatch, capsys
) -> None:
    """The sweep stops processing new candidates once its time budget elapses.

    The sweep-organization-agent-mentions job has a 15-minute GitHub Actions
    timeout; a hard cancellation on that deadline discards the run's log
    tail and metrics. The sweep must instead stop itself with margin to
    spare and report what it completed.

    list_recent_pull_requests submits every repository's fetch to a bounded
    ThreadPoolExecutor up front (see the comment above the loop in sweep()),
    so a fake per-candidate generator here does not model which repository
    fetches actually started — only that this loop stops PROCESSING
    (building requests for) a candidate once the deadline has passed, even
    though the candidate itself was already yielded.
    """

    sweep = module()
    processed = []

    def recording_candidates(*args, **kwargs):
        """Yield three already-available candidates."""

        del args, kwargs
        yield from (candidate(1), candidate(2), candidate(3))

    def recording_build_requests(client, *, issue, since):
        """Record which candidate reached request-building and return none."""

        del client, since
        processed.append(issue["number"])
        return ()

    monkeypatch.setattr(sweep, "list_recent_pull_requests", recording_candidates)
    monkeypatch.setattr(
        sweep, "build_requests_for_pull_request", recording_build_requests
    )
    # One clock read to compute the deadline, then one read per loop
    # iteration: under budget, under budget, over budget on the third.
    clock_reads = iter([0.0, 10.0, 60.0, 200.0])
    result = sweep.sweep(
        target_client=FakeClient(),
        dispatch_client=FakeClient(),
        organization="ContextualWisdomLab",
        repository_source="organization",
        lookback_hours=24,
        max_dispatches=5,
        opencode_allowlist=frozenset(),
        now=datetime(2026, 8, 5, tzinfo=timezone.utc),
        time_budget_seconds=100.0,
        clock=lambda: next(clock_reads),
    )

    assert result == 0
    assert processed == [1, 2]
    assert "time budget" in capsys.readouterr().out


def test_sweep_time_budget_can_be_disabled(monkeypatch) -> None:
    """Passing None for the time budget preserves unbounded iteration."""

    sweep = module()
    monkeypatch.setattr(
        sweep, "list_recent_pull_requests", lambda *args, **kwargs: iter(())
    )

    def forbidden_clock() -> float:
        """Fail the test if the disabled budget still reads the clock."""

        raise AssertionError("clock should not be read when disabled")

    assert (
        sweep.sweep(
            target_client=FakeClient(),
            dispatch_client=FakeClient(),
            organization="ContextualWisdomLab",
            repository_source="organization",
            lookback_hours=24,
            max_dispatches=5,
            opencode_allowlist=frozenset(),
            time_budget_seconds=None,
            clock=forbidden_clock,
        )
        == 0
    )
    with pytest.raises(ValueError, match="time budget"):
        sweep.sweep(
            target_client=FakeClient(),
            dispatch_client=FakeClient(),
            organization="ContextualWisdomLab",
            repository_source="organization",
            lookback_hours=24,
            max_dispatches=5,
            opencode_allowlist=frozenset(),
            time_budget_seconds=0.0,
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


@pytest.mark.parametrize(
    "organization",
    ["..", "...", ".leading", "trailing.", "double..dot", "mid..dle.evil"],
)
def test_org_name_re_rejects_dot_traversal_boundaries(organization: str) -> None:
    """ORG_NAME_RE rejects leading/trailing dots and any ".." run."""

    sweep = module()
    assert sweep.ORG_NAME_RE.fullmatch(organization) is None


@pytest.mark.parametrize(
    "organization", ["ContextualWisdomLab", "org-name", "org.name", "org_name"]
)
def test_org_name_re_accepts_a_single_interior_dot(organization: str) -> None:
    """ORG_NAME_RE still accepts ordinary single-dot organization names."""

    sweep = module()
    assert sweep.ORG_NAME_RE.fullmatch(organization) is not None


@pytest.mark.parametrize(
    "repository",
    [
        "ContextualWisdomLab/.",
        "ContextualWisdomLab/..",
        "ContextualWisdomLab/...",
    ],
)
def test_repository_re_rejects_all_dot_traversal_segments(repository: str) -> None:
    """REPOSITORY_RE rejects a repo-name segment that is entirely dots.

    This is the traversal class this boundary exists to stop: a segment of
    only dots is the value GitHub API/URL path resolution treats specially
    (e.g. "owner/.." can escape the intended path when interpolated into a
    later request URL).
    """

    sweep = module()
    assert sweep.REPOSITORY_RE.fullmatch(repository) is None


@pytest.mark.parametrize(
    "repository",
    [
        "ContextualWisdomLab/.github",
        "ContextualWisdomLab/example",
        "ContextualWisdomLab/foo.bar",
    ],
)
def test_repository_re_still_accepts_real_dotted_repo_names(repository: str) -> None:
    """REPOSITORY_RE keeps accepting real repos, including the org's own
    dot-prefixed ".github" special repository."""

    sweep = module()
    assert sweep.REPOSITORY_RE.fullmatch(repository) is not None
