#!/usr/bin/env python3
"""Sweep recent CWL pull-request comments for explicit source-fix commands."""

from __future__ import annotations

import argparse
import os
import time
from datetime import datetime, timezone
from typing import Any, Callable

from agent_mention_router import GitHubClient, parse_repository_allowlist
from agent_mention_sweep import (
    DEFAULT_TIME_BUDGET_SECONDS,
    REPOSITORY_ROTATION_SECONDS,
    SweepMetrics,
    cutoff_timestamp,
    list_recent_comments,
    list_recent_pull_requests,
)
from agent_source_fix_router import dispatch_request, parse_event
from redact_sensitive_log import redact_text


def build_requests_for_pull_request(
    client: GitHubClient,
    *,
    issue: dict[str, Any],
    since: str,
):
    repository = str(issue.get("repository") or "")
    number = issue.get("number")
    comments = list_recent_comments(
        client,
        repository=repository,
        pull_request_number=number,
        since=since,
    )
    live_pull = client.request([f"repos/{repository}/pulls/{number}"])
    if not isinstance(live_pull, dict) or live_pull.get("state") != "open":
        return ()
    requests = []
    for comment in comments:
        request = parse_event(
            {
                "repository": {"full_name": repository},
                "issue": {"number": number, "pull_request": issue.get("pull_request")},
                "comment": comment,
                "pull_request": live_pull,
            }
        )
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
    repository_allowlist: frozenset[str],
    dry_run: bool = False,
    now: datetime | None = None,
    time_budget_seconds: float | None = DEFAULT_TIME_BUDGET_SECONDS,
    clock: Callable[[], float] = time.monotonic,
) -> tuple[int, int]:
    if max_dispatches < 1 or max_dispatches > 100:
        raise ValueError("max dispatches must be between 1 and 100")
    current = now or datetime.now(timezone.utc)
    since = cutoff_timestamp(lookback_hours, now=current)
    rotation_offset = int(current.timestamp() // REPOSITORY_ROTATION_SECONDS)
    metrics = SweepMetrics()
    dispatched = 0
    deadline = None if time_budget_seconds is None else clock() + time_budget_seconds

    def record_failure(scope: str, error: Exception) -> None:
        metrics.failures += 1
        message = redact_text(" ".join(str(error).split())) or error.__class__.__name__
        print(f"::warning::Source-fix sweep skipped {scope}: {message[:1000]}")

    try:
        for issue in list_recent_pull_requests(
            target_client,
            organization=organization,
            repository_source=repository_source,
            since=since,
            on_error=record_failure,
            rotation_offset=rotation_offset,
        ):
            if deadline is not None and clock() >= deadline:
                break
            scope = f"{issue.get('repository')}#{issue.get('number')}"
            try:
                requests = build_requests_for_pull_request(target_client, issue=issue, since=since)
            except Exception as exc:  # noqa: BLE001 - isolate one PR
                record_failure(scope, exc)
                continue
            for request in requests:
                if dispatched >= max_dispatches:
                    return dispatched, metrics.failures
                try:
                    if dispatch_request(
                        request,
                        target_client=target_client,
                        dispatch_client=dispatch_client,
                        repository_allowlist=repository_allowlist,
                        dry_run=dry_run,
                    ):
                        dispatched += 1
                except Exception as exc:  # noqa: BLE001 - isolate one comment
                    record_failure(f"{scope}/comment-{request.comment_id}", exc)
    except Exception as exc:  # noqa: BLE001 - organization listing boundary
        record_failure("organization-listing", exc)
    return dispatched, metrics.failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--organization", default="ContextualWisdomLab")
    parser.add_argument("--repository-source", choices=("organization", "installation"), required=True)
    parser.add_argument("--lookback-hours", type=int, default=168)
    parser.add_argument("--max-dispatches", type=int, default=20)
    parser.add_argument("--time-budget-seconds", type=float, default=480.0)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    target_token = os.environ.get("TARGET_REPOSITORY_TOKEN") or os.environ.get("GH_TOKEN", "")
    dispatch_token = os.environ.get("AGENT_DISPATCH_TOKEN") or os.environ.get("GH_TOKEN", "")
    allowlist_raw = os.environ.get("SOURCE_FIX_REPOSITORY_TARGETS") or os.environ.get(
        "OPENCODE_REPOSITORY_DISPATCH_TARGETS", ""
    )
    dispatched, failures = sweep(
        target_client=GitHubClient(target_token),
        dispatch_client=GitHubClient(dispatch_token),
        organization=args.organization,
        repository_source=args.repository_source,
        lookback_hours=args.lookback_hours,
        max_dispatches=args.max_dispatches,
        repository_allowlist=parse_repository_allowlist(allowlist_raw),
        dry_run=args.dry_run,
        time_budget_seconds=args.time_budget_seconds,
    )
    print(f"Source-fix sweep: {dispatched} dispatch(es), {failures} isolated failure(s).")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
