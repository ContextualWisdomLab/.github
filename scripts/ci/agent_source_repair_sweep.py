#!/usr/bin/env python3
"""Sweep recent CWL pull-request comments for explicit source-repair commands."""

from __future__ import annotations

import argparse
import os
import time
from datetime import datetime, timezone
from typing import Sequence

try:  # pragma: no cover - direct-script import compatibility
    from agent_mention_router import GitHubClient  # pragma: no cover
    from agent_mention_sweep import (
        DEFAULT_TIME_BUDGET_SECONDS,
        REPOSITORY_ROTATION_SECONDS,
        cutoff_timestamp,
        list_recent_comments,
        list_recent_pull_requests,
    )
    from agent_source_repair import (
        TRUSTED_ASSOCIATIONS,
        SourceRepairAlreadyClaimed,
        SourceRepairError,
        SourceRepairNotEnabled,
        SourceRepairNotRequested,
        dispatch_source_repair,
        expected_from_comment,
    )
    from redact_sensitive_log import redact_text
except ModuleNotFoundError:  # pragma: no cover
    from scripts.ci.agent_mention_router import GitHubClient  # pragma: no cover
    from scripts.ci.agent_mention_sweep import (
        DEFAULT_TIME_BUDGET_SECONDS,
        REPOSITORY_ROTATION_SECONDS,
        cutoff_timestamp,
        list_recent_comments,
        list_recent_pull_requests,
    )
    from scripts.ci.agent_source_repair import (
        TRUSTED_ASSOCIATIONS,
        SourceRepairAlreadyClaimed,
        SourceRepairError,
        SourceRepairNotEnabled,
        SourceRepairNotRequested,
        dispatch_source_repair,
        expected_from_comment,
    )
    from scripts.ci.redact_sensitive_log import redact_text


def _trusted_human_comment(comment: object) -> bool:
    """Return whether one comment may consume source-repair validation resources."""

    if not isinstance(comment, dict):
        return False
    user = comment.get("user") or {}
    if not isinstance(user, dict):
        return False
    if str(user.get("type") or "").casefold() == "bot":
        return False
    return str(comment.get("author_association") or "").upper() in TRUSTED_ASSOCIATIONS


def sweep_source_repairs(
    *,
    target_client: GitHubClient,
    dispatch_client: GitHubClient,
    organization: str,
    repository_source: str,
    lookback_hours: int,
    max_dispatches: int,
    dry_run: bool = False,
    now: datetime | None = None,
    time_budget_seconds: float | None = DEFAULT_TIME_BUDGET_SECONDS,
) -> tuple[int, int]:
    """Dispatch bounded explicit repairs while isolating candidate-local rejection/failure."""

    if max_dispatches < 1 or max_dispatches > 100:
        raise ValueError("max dispatches must be between 1 and 100")
    if time_budget_seconds is not None and time_budget_seconds <= 0:
        raise ValueError("time budget must be positive when set")
    current = now or datetime.now(timezone.utc)
    since = cutoff_timestamp(lookback_hours, now=current)
    rotation_offset = int(current.timestamp() // REPOSITORY_ROTATION_SECONDS)
    deadline = None if time_budget_seconds is None else time.monotonic() + time_budget_seconds
    dispatched = 0
    failures = 0

    def warn(scope: str, error: Exception) -> None:
        """Report one isolated failure without exposing credential-shaped diagnostics."""

        nonlocal failures
        failures += 1
        text = redact_text(" ".join(str(error).split())) or error.__class__.__name__
        print(f"::warning::Source-repair sweep skipped {scope}: {text[:1000]}")

    try:
        candidates = list_recent_pull_requests(
            target_client,
            organization=organization,
            repository_source=repository_source,
            since=since,
            on_error=warn,
            rotation_offset=rotation_offset,
        )
        for issue in candidates:
            if deadline is not None and time.monotonic() >= deadline:
                print(
                    "Source-repair sweep stopped before its time budget; "
                    f"dispatches={dispatched} failures={failures}."
                )
                return dispatched, failures
            repository = str(issue.get("repository") or "")
            number = int(issue.get("number") or 0)
            scope = f"{repository}#{number}"
            try:
                comments = list_recent_comments(
                    target_client,
                    repository=repository,
                    pull_request_number=number,
                    since=since,
                )
                trusted_comments = [
                    comment for comment in comments if _trusted_human_comment(comment)
                ]
                if not trusted_comments:
                    continue
                pull_request = target_client.request(
                    [f"repos/{repository}/pulls/{number}", "-X", "GET"]
                )
                if not isinstance(pull_request, dict) or pull_request.get("state") != "open":
                    continue
            except Exception as exc:  # noqa: BLE001 - isolate one target PR
                warn(scope, exc)
                continue

            for comment in trusted_comments:
                comment_id = int(comment.get("id") or 0)
                command_scope = f"{scope}/comment-{comment_id}"
                try:
                    expected = expected_from_comment(
                        repository,
                        number,
                        pull_request,
                        comment,
                    )
                    queued = dispatch_source_repair(
                        target_client=target_client,
                        dispatch_client=dispatch_client,
                        expected=expected,
                        dry_run=dry_run,
                    )
                except (SourceRepairNotRequested, SourceRepairNotEnabled, SourceRepairAlreadyClaimed):
                    continue
                except SourceRepairError as exc:
                    warn(command_scope, exc)
                    continue
                except Exception as exc:  # noqa: BLE001 - isolate one command
                    warn(command_scope, exc)
                    continue
                if not queued:
                    continue
                dispatched += 1
                if dispatched >= max_dispatches:
                    print(
                        f"Source-repair sweep reached dispatch limit {max_dispatches}; "
                        f"failures={failures}."
                    )
                    return dispatched, failures
    except Exception as exc:  # noqa: BLE001 - repository inventory boundary
        warn(f"{organization} repository listing", exc)
    print(f"Source-repair sweep completed: dispatches={dispatched} failures={failures}.")
    return dispatched, failures


def main(argv: Sequence[str] | None = None) -> int:
    """Run the bounded organization source-repair sweep."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--organization", default="ContextualWisdomLab")
    parser.add_argument(
        "--repository-source",
        choices=("organization", "installation"),
        default="installation",
    )
    parser.add_argument("--lookback-hours", type=int, default=24)
    parser.add_argument("--max-dispatches", type=int, default=10)
    parser.add_argument(
        "--time-budget-seconds",
        type=float,
        default=DEFAULT_TIME_BUDGET_SECONDS,
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    target_token = os.environ.get("TARGET_REPOSITORY_TOKEN", "")
    dispatch_token = os.environ.get("AGENT_DISPATCH_TOKEN", "")
    if not target_token or not dispatch_token:
        parser.error("TARGET_REPOSITORY_TOKEN and AGENT_DISPATCH_TOKEN are required")
    _, failures = sweep_source_repairs(
        target_client=GitHubClient(target_token),
        dispatch_client=GitHubClient(dispatch_token),
        organization=args.organization,
        repository_source=args.repository_source,
        lookback_hours=args.lookback_hours,
        max_dispatches=args.max_dispatches,
        dry_run=args.dry_run,
        time_budget_seconds=(
            None if args.time_budget_seconds <= 0 else args.time_budget_seconds
        ),
    )
    return 1 if failures else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
