#!/usr/bin/env python3
"""Sweep recent CWL pull-request comments for trusted review-agent mentions."""

from __future__ import annotations

import argparse
import concurrent.futures
import os
import re
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterator, Sequence

from agent_mention_router import (
    GitHubClient,
    MentionRequest,
    dispatch_request,
    parse_event,
    parse_repository_allowlist,
)

ORG_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
REPOSITORY_RE = re.compile(r"^ContextualWisdomLab/[A-Za-z0-9_.-]+$")
REPOSITORY_SOURCES = frozenset({"organization", "installation"})
REPOSITORY_ROTATION_SECONDS = 5 * 60


@dataclass
class SweepMetrics:
    """Mutable operational counters returned to the CLI boundary."""

    failures: int = 0


def parse_timestamp(value: str) -> datetime:
    """Parse one GitHub ISO-8601 timestamp into timezone-aware UTC."""

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise ValueError("invalid GitHub timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError("GitHub timestamp must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def cutoff_timestamp(lookback_hours: int, *, now: datetime | None = None) -> str:
    """Return an ISO-8601 UTC cutoff for the bounded comment lookback window."""

    if lookback_hours < 1 or lookback_hours > 24 * 30:
        raise ValueError("lookback hours must be between 1 and 720")
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("current time must be timezone-aware")
    cutoff = current.astimezone(timezone.utc) - timedelta(hours=lookback_hours)
    return cutoff.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def flatten_pages(
    value: Any,
    *,
    collection_key: str | None = None,
) -> list[dict[str, Any]]:
    """Flatten ``gh api --paginate --slurp`` output into object records."""

    if value is None:
        raise ValueError("paginated GitHub response is empty")
    if (
        collection_key is None
        and isinstance(value, list)
        and all(isinstance(record, dict) for record in value)
    ):
        return list(value)
    pages = value if isinstance(value, list) else [value]
    records: list[dict[str, Any]] = []
    for page in pages:
        if collection_key and not isinstance(page, dict):
            raise ValueError("paginated GitHub response page is not an object")
        collection = page.get(collection_key, []) if collection_key else page
        if not isinstance(collection, list):
            raise ValueError("paginated GitHub response is not a list")
        if not all(isinstance(record, dict) for record in collection):
            raise ValueError(
                "paginated GitHub response contains a non-object record"
            )
        records.extend(collection)
    return records


def list_accessible_repositories(
    client: GitHubClient,
    *,
    organization: str,
    repository_source: str,
) -> list[str]:
    """List active organization repositories visible to the selected token type."""

    if not ORG_NAME_RE.fullmatch(organization):
        raise ValueError("invalid organization name")
    if repository_source not in REPOSITORY_SOURCES:
        raise ValueError("repository source must be organization or installation")
    if repository_source == "installation":
        response = client.request(
            [
                "installation/repositories",
                "-X",
                "GET",
                "-f",
                "per_page=100",
                "--paginate",
                "--slurp",
            ]
        )
        repositories = flatten_pages(response, collection_key="repositories")
    else:
        response = client.request(
            [
                f"orgs/{organization}/repos",
                "-X",
                "GET",
                "-f",
                "type=all",
                "-f",
                "per_page=100",
                "--paginate",
                "--slurp",
            ]
        )
        repositories = flatten_pages(response)
    names: list[str] = []
    for repository in repositories:
        full_name = str(repository.get("full_name") or "")
        owner = str(repository.get("owner", {}).get("login") or "")
        if owner.casefold() != organization.casefold():
            continue
        if repository.get("archived") or repository.get("disabled"):
            continue
        if not REPOSITORY_RE.fullmatch(full_name):
            raise ValueError("GitHub returned an invalid repository full_name")
        names.append(full_name)
    return sorted(set(names))


def list_recent_pull_requests(
    client: GitHubClient,
    *,
    organization: str,
    repository_source: str,
    since: str,
    on_error: Callable[[str, Exception], None] | None = None,
    rotation_offset: int = 0,
) -> Iterator[dict[str, Any]]:
    """Yield recent open pull requests with bounded fair repository rotation."""

    cutoff = parse_timestamp(since)
    repositories = list_accessible_repositories(
        client,
        organization=organization,
        repository_source=repository_source,
    )
    if not repositories:
        return
    rotation_offset %= len(repositories)
    repositories = repositories[rotation_offset:] + repositories[:rotation_offset]
    stop_event = threading.Event()

    def fetch(repository: str) -> list[dict[str, Any]]:
        """Fetch one repository's recent open pull requests."""

        results: list[dict[str, Any]] = []
        page = 1
        while not stop_event.is_set():
            response = client.request(
                [
                    f"repos/{repository}/pulls",
                    "-X",
                    "GET",
                    "-f",
                    "state=open",
                    "-f",
                    "sort=updated",
                    "-f",
                    "direction=desc",
                    "-f",
                    "per_page=100",
                    "-f",
                    f"page={page}",
                ]
            )
            pull_requests = flatten_pages(response)
            if not pull_requests:
                break
            reached_cutoff = False
            for pull_request in pull_requests:
                if parse_timestamp(str(pull_request.get("updated_at") or "")) < cutoff:
                    reached_cutoff = True
                    break
                number = pull_request.get("number")
                if not isinstance(number, int) or number < 1:
                    raise ValueError("GitHub returned an invalid pull request number")
                results.append(
                    {
                        "number": number,
                        "repository": repository,
                        "pull_request": {
                            "url": (
                                "https://api.github.com/repos/"
                                f"{repository}/pulls/{number}"
                            )
                        },
                    }
                )
            if reached_cutoff or len(pull_requests) < 100:
                break
            page += 1
        return results

    executor = concurrent.futures.ThreadPoolExecutor(
        max_workers=min(4, len(repositories))
    )
    futures = [
        (repository, executor.submit(fetch, repository))
        for repository in repositories
    ]
    try:
        for repository, future in futures:
            try:
                yield from future.result()
            except Exception as exc:  # noqa: BLE001 - repository isolation boundary
                if on_error is None:
                    raise
                on_error(repository, exc)
    finally:
        stop_event.set()
        for _, future in futures:
            future.cancel()
        executor.shutdown(wait=True, cancel_futures=True)


def list_recent_comments(
    client: GitHubClient,
    *,
    repository: str,
    pull_request_number: int,
    since: str,
) -> list[dict[str, Any]]:
    """List recent issue comments for one pull request."""

    response = client.request(
        [
            f"repos/{repository}/issues/{pull_request_number}/comments",
            "-X",
            "GET",
            "-f",
            f"since={since}",
            "-f",
            "per_page=100",
            "--paginate",
            "--slurp",
        ]
    )
    return flatten_pages(response)


def build_requests_for_pull_request(
    client: GitHubClient,
    *,
    issue: dict[str, Any],
    since: str,
) -> tuple[MentionRequest, ...]:
    """Build trusted mention requests for one live pull request."""

    repository = str(issue.get("repository") or "")
    if not REPOSITORY_RE.fullmatch(repository):
        raise ValueError("pull request candidate has an invalid repository")
    number = issue.get("number")
    if not isinstance(number, int) or number < 1:
        raise ValueError("pull request candidate has an invalid number")
    comments = list_recent_comments(
        client,
        repository=repository,
        pull_request_number=number,
        since=since,
    )
    live_pull = client.request([f"repos/{repository}/pulls/{number}"])
    if not isinstance(live_pull, dict) or live_pull.get("state") != "open":
        return ()
    requests: list[MentionRequest] = []
    for comment in comments:
        event = {
            "repository": {"full_name": repository},
            "issue": {
                "number": number,
                "pull_request": issue.get("pull_request"),
            },
            "comment": comment,
            "pull_request": live_pull,
        }
        request = parse_event(event)
        if request is not None:
            requests.append(request)
    return tuple(requests)


def sweep(
    *,
    target_client: GitHubClient,
    dispatch_client: GitHubClient,
    organization: str,
    repository_source: str,
    lookback_hours: int,
    max_dispatches: int,
    opencode_allowlist: frozenset[str],
    dry_run: bool = False,
    now: datetime | None = None,
    metrics: SweepMetrics | None = None,
) -> int:
    """Queue bounded new work while isolating candidate-local failures."""

    if max_dispatches < 1 or max_dispatches > 100:
        raise ValueError("max dispatches must be between 1 and 100")
    current = now or datetime.now(timezone.utc)
    since = cutoff_timestamp(lookback_hours, now=current)
    rotation_offset = int(current.timestamp() // REPOSITORY_ROTATION_SECONDS)
    counters = metrics if metrics is not None else SweepMetrics()
    ledger_artifact_cache: dict[str, bool] = {}
    dispatched = 0

    def record_failure(scope: str, error: Exception) -> None:
        """Record one isolated error and preserve the remaining sweep."""

        counters.failures += 1
        message = " ".join(str(error).split()) or error.__class__.__name__
        print(
            f"::warning::Agent mention sweep skipped {scope}: {message[:1000]}"
        )

    for issue in list_recent_pull_requests(
        target_client,
        organization=organization,
        repository_source=repository_source,
        since=since,
        on_error=record_failure,
        rotation_offset=rotation_offset,
    ):
        issue_scope = f"{issue.get('repository')}#{issue.get('number')}"
        try:
            requests = build_requests_for_pull_request(
                target_client,
                issue=issue,
                since=since,
            )
        except Exception as exc:  # noqa: BLE001 - pull-request isolation boundary
            record_failure(issue_scope, exc)
            continue
        for request in requests:
            request_scope = f"{issue_scope}/comment-{request.comment_id}"
            try:
                queued_agents = dispatch_request(
                    request,
                    target_client=target_client,
                    dispatch_client=dispatch_client,
                    opencode_allowlist=opencode_allowlist,
                    dry_run=dry_run,
                    ledger_artifact_cache=ledger_artifact_cache,
                )
            except Exception as exc:  # noqa: BLE001 - request isolation boundary
                record_failure(request_scope, exc)
                continue
            if not queued_agents:
                continue
            dispatched += 1
            if dispatched >= max_dispatches:
                print(
                    "Agent mention sweep reached dispatch limit "
                    f"{max_dispatches}; isolated failures={counters.failures}."
                )
                return dispatched
    print(
        "Agent mention sweep completed with "
        f"{dispatched} dispatch(es) and {counters.failures} isolated failure(s)."
    )
    return dispatched


def main(argv: Sequence[str] | None = None) -> int:
    """Run the scheduled organization mention sweep."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--organization", default="ContextualWisdomLab")
    parser.add_argument(
        "--repository-source",
        choices=sorted(REPOSITORY_SOURCES),
        default="organization",
    )
    parser.add_argument("--lookback-hours", type=int, default=168)
    parser.add_argument("--max-dispatches", type=int, default=20)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    allowlist = parse_repository_allowlist(
        os.environ.get("OPENCODE_REPOSITORY_DISPATCH_TARGETS", "")
    )
    metrics = SweepMetrics()
    sweep(
        target_client=GitHubClient(
            os.environ.get("TARGET_REPOSITORY_TOKEN", "")
        ),
        dispatch_client=GitHubClient(os.environ.get("AGENT_DISPATCH_TOKEN", "")),
        organization=args.organization,
        repository_source=args.repository_source,
        lookback_hours=args.lookback_hours,
        max_dispatches=args.max_dispatches,
        opencode_allowlist=allowlist,
        dry_run=args.dry_run,
        metrics=metrics,
    )
    return 1 if metrics.failures else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
