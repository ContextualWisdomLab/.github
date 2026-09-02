#!/usr/bin/env python3
"""Retire stale central semantic-review dispatches without touching current-head evidence.

The central reviewer workflows execute from ContextualWisdomLab/.github after a
trusted ``repository_dispatch``. GitHub does not emit a matching central event
when a target pull request later closes, and a newly queued target-repository
scheduler may itself wait behind the saturated Actions fleet. This module
therefore performs a bounded trusted sweep of already-active central review
runs and force-cancels only runs whose exact target is proven closed or whose
recorded head is proven different from the live open pull request head.

Malformed run metadata, unavailable pull-request metadata, and the exact current
open head are preserved. The script never executes pull-request source.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import re
import subprocess
from collections.abc import Callable, Iterable
from typing import Any

CENTRAL_REPOSITORY = "ContextualWisdomLab/.github"
ACTIVE_STATUSES = ("queued", "in_progress")
REVIEW_WORKFLOW_NAMES = frozenset(
    {
        "OpenCode Review Dispatch",
        "Required OpenCode Review",
        "Required Noema Review",
        "Strix Security Scan",
    }
)
_TITLE_RE = re.compile(
    r"^(?P<title>.+?) (?P<repository>ContextualWisdomLab/[A-Za-z0-9_.-]+)"
    r"#(?P<pr_number>[1-9][0-9]*)@(?P<head_sha>[0-9a-fA-F]{40})$"
)


@dataclasses.dataclass(frozen=True)
class ReviewDispatch:
    """Validated identity of one active central semantic-review dispatch."""

    run_id: str
    workflow_name: str
    repository: str
    pr_number: int
    head_sha: str


@dataclasses.dataclass
class ReapSummary:
    """Auditable counters for one stale-dispatch sweep."""

    cancelled_closed: int = 0
    cancelled_stale_head: int = 0
    preserved_current: int = 0
    metadata_unavailable: int = 0
    ignored: int = 0


def parse_review_dispatch(run_data: dict[str, Any]) -> ReviewDispatch | None:
    """Return trusted target identity for one central review dispatch run."""
    if run_data.get("event") != "repository_dispatch":
        return None
    workflow_name = str(run_data.get("name") or "")
    if workflow_name not in REVIEW_WORKFLOW_NAMES:
        return None
    run_id = run_data.get("id")
    if run_id is None:
        return None
    title = str(run_data.get("display_title") or "")
    match = _TITLE_RE.fullmatch(title)
    if match is None:
        return None
    if match.group("title") != workflow_name:
        return None
    return ReviewDispatch(
        run_id=str(run_id),
        workflow_name=workflow_name,
        repository=match.group("repository"),
        pr_number=int(match.group("pr_number")),
        head_sha=match.group("head_sha").lower(),
    )


def reap_review_dispatches(
    runs: Iterable[dict[str, Any]],
    *,
    fetch_pr: Callable[[str, int], dict[str, Any]],
    cancel: Callable[[str], None],
) -> ReapSummary:
    """Cancel only proven closed-target or previous-head central review runs."""
    summary = ReapSummary()
    live_cache: dict[tuple[str, int], dict[str, Any] | None] = {}
    for run_data in runs:
        target = parse_review_dispatch(run_data)
        if target is None:
            summary.ignored += 1
            continue
        cache_key = (target.repository, target.pr_number)
        if cache_key not in live_cache:
            try:
                live_cache[cache_key] = fetch_pr(*cache_key)
            except Exception as exc:  # noqa: BLE001 - unavailable evidence preserves the run
                print(
                    "metadata_unavailable "
                    f"target={target.repository}#{target.pr_number} "
                    f"error_type={type(exc).__name__}"
                )
                live_cache[cache_key] = None
        live_pr = live_cache[cache_key]
        if live_pr is None:
            summary.metadata_unavailable += 1
            continue
        live_state = str(live_pr.get("state") or "").lower()
        live_head = str(((live_pr.get("head") or {}).get("sha")) or "").lower()
        if live_state != "open":
            cancel(target.run_id)
            summary.cancelled_closed += 1
            continue
        if not re.fullmatch(r"[0-9a-f]{40}", live_head):
            summary.metadata_unavailable += 1
            continue
        if live_head != target.head_sha:
            cancel(target.run_id)
            summary.cancelled_stale_head += 1
            continue
        summary.preserved_current += 1
    return summary


def _run_gh_json(args: list[str], *, token: str) -> Any:
    """Run one gh API read with a caller-selected credential."""
    env = os.environ.copy()
    env["GH_TOKEN"] = token
    process = subprocess.run(
        ["gh", *args],
        check=True,
        capture_output=True,
        text=True,
        shell=False,
        env=env,
    )
    return json.loads(process.stdout)


def active_central_review_runs(actions_token: str) -> list[dict[str, Any]]:
    """Return every queued/in-progress central repository-dispatch run."""
    runs: list[dict[str, Any]] = []
    for status in ACTIVE_STATUSES:
        payload = _run_gh_json(
            [
                "api",
                "--method",
                "GET",
                f"repos/{CENTRAL_REPOSITORY}/actions/runs",
                "--paginate",
                "--slurp",
                "-f",
                f"status={status}",
                "-f",
                "event=repository_dispatch",
                "-F",
                "per_page=100",
            ],
            token=actions_token,
        )
        pages = payload if isinstance(payload, list) else [payload]
        for page in pages:
            runs.extend(page.get("workflow_runs") or [])
    return runs


def fetch_pull_request(repository: str, pr_number: int, *, token: str) -> dict[str, Any]:
    """Read one target pull request without exposing its body or source."""
    return _run_gh_json(
        ["api", f"repos/{repository}/pulls/{pr_number}"],
        token=token,
    )


def force_cancel_central_run(run_id: str, *, token: str) -> None:
    """Force-cancel one proven stale central Actions run."""
    env = os.environ.copy()
    env["GH_TOKEN"] = token
    subprocess.run(
        [
            "gh",
            "api",
            "-X",
            "POST",
            f"repos/{CENTRAL_REPOSITORY}/actions/runs/{run_id}/force-cancel",
        ],
        check=True,
        capture_output=True,
        text=True,
        shell=False,
        env=env,
    )


def main() -> int:
    """Execute one trusted stale-dispatch sweep."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY", ""))
    args = parser.parse_args()
    if args.repository != CENTRAL_REPOSITORY:
        raise SystemExit(
            f"refusing stale review dispatch reaping outside {CENTRAL_REPOSITORY}"
        )
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise SystemExit("refusing stale review dispatch reaping outside GitHub Actions")
    actions_token = os.environ.get("GH_TOKEN") or ""
    read_token = os.environ.get("SCHEDULER_READ_TOKEN") or actions_token
    if not actions_token:
        raise SystemExit("GH_TOKEN is required for central Actions cancellation")
    runs = active_central_review_runs(actions_token)
    summary = reap_review_dispatches(
        runs,
        fetch_pr=lambda repository, pr_number: fetch_pull_request(
            repository, pr_number, token=read_token
        ),
        cancel=lambda run_id: force_cancel_central_run(run_id, token=actions_token),
    )
    print(
        "review_dispatch_reap "
        f"cancelled_closed={summary.cancelled_closed} "
        f"cancelled_stale_head={summary.cancelled_stale_head} "
        f"preserved_current={summary.preserved_current} "
        f"metadata_unavailable={summary.metadata_unavailable} "
        f"ignored={summary.ignored}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
