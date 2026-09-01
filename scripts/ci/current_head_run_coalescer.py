#!/usr/bin/env python3
"""Retire redundant queued GitHub Actions runs for one exact open PR head.

The coalescer is intentionally narrower than ordinary stale-head cleanup. It
never cancels an in-progress run and never cancels the only queued run for a
workflow. A queued candidate is eligible only when a distinct same-workflow,
same-repository, same-branch, same-head pull-request run is still active after
live PR and Actions state are re-fetched immediately before cancellation.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from typing import Any, Iterable, Sequence


GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
REPOSITORY_RE = re.compile(
    r"^(?!\.{1,2}/)[A-Za-z0-9_.-]+/(?!\.{1,2}$)[A-Za-z0-9_.-]+$"
)
PR_EVENTS = frozenset({"pull_request", "pull_request_target"})
ACTIVE_STATUSES = ("queued", "in_progress")


class CoalescingRefused(RuntimeError):
    """Signal that live evidence is insufficient for a destructive cancellation."""


def _positive_int(value: object) -> int | None:
    """Return a positive integer without accepting booleans or numeric strings."""
    return value if type(value) is int and value > 0 else None


def _run_identity_matches(
    run_data: dict[str, Any],
    *,
    repository: str,
    branch: str,
    head_sha: str,
) -> bool:
    """Return whether one run belongs to the exact PR-head cancellation boundary."""
    return (
        run_data.get("event") in PR_EVENTS
        and str(run_data.get("head_sha") or "").lower() == head_sha
        and run_data.get("head_branch") == branch
        and ((run_data.get("head_repository") or {}).get("full_name") == repository)
        and _positive_int(run_data.get("workflow_id")) is not None
        and _positive_int(run_data.get("id")) is not None
        and run_data.get("status") in ACTIVE_STATUSES
    )


def select_duplicate_queued_run_ids(
    runs: Iterable[dict[str, Any]],
    *,
    repository: str,
    branch: str,
    head_sha: str,
) -> list[int]:
    """Select only redundant queued runs while retaining authoritative siblings.

    Runs are grouped by GitHub's stable numeric ``workflow_id`` after exact
    repository/branch/head/event filtering. If a workflow already has an
    in-progress run, every queued sibling is redundant. Otherwise the newest
    queued run ID is retained and only older queued siblings are selected.
    In-progress runs are never returned.
    """
    groups: dict[int, list[dict[str, Any]]] = {}
    for run_data in runs:
        if not _run_identity_matches(
            run_data, repository=repository, branch=branch, head_sha=head_sha
        ):
            continue
        workflow_id = _positive_int(run_data.get("workflow_id"))
        if workflow_id is not None:
            groups.setdefault(workflow_id, []).append(run_data)

    redundant: list[int] = []
    for group in groups.values():
        queued = [item for item in group if item.get("status") == "queued"]
        if not queued:
            continue
        if any(item.get("status") == "in_progress" for item in group):
            redundant.extend(
                run_id
                for item in queued
                if (run_id := _positive_int(item.get("id"))) is not None
            )
            continue
        queued_ids = sorted(
            run_id
            for item in queued
            if (run_id := _positive_int(item.get("id"))) is not None
        )
        if len(queued_ids) > 1:
            redundant.extend(queued_ids[:-1])
    return sorted(redundant)


def validate_candidate_against_live_state(
    candidate: dict[str, Any],
    *,
    live_pr: dict[str, Any],
    active_same_head_runs: Sequence[dict[str, Any]],
) -> None:
    """Fail closed unless a queued candidate still has an authoritative sibling."""
    if candidate.get("status") != "queued":
        raise CoalescingRefused("candidate is no longer queued")
    if live_pr.get("state") != "open":
        raise CoalescingRefused("pull request is no longer open")

    live_head = live_pr.get("head") or {}
    live_repo = ((live_head.get("repo") or {}).get("full_name") or "")
    live_ref = str(live_head.get("ref") or "")
    live_sha = str(live_head.get("sha") or "").lower()
    candidate_repo = ((candidate.get("head_repository") or {}).get("full_name") or "")
    candidate_ref = str(candidate.get("head_branch") or "")
    candidate_sha = str(candidate.get("head_sha") or "").lower()
    if (
        not GIT_SHA_RE.fullmatch(live_sha)
        or live_sha != candidate_sha
        or live_ref != candidate_ref
        or live_repo != candidate_repo
    ):
        raise CoalescingRefused("pull request head moved after duplicate classification")

    candidate_id = _positive_int(candidate.get("id"))
    workflow_id = _positive_int(candidate.get("workflow_id"))
    if candidate_id is None or workflow_id is None:
        raise CoalescingRefused("candidate identity is malformed")
    if candidate.get("event") not in PR_EVENTS:
        raise CoalescingRefused("candidate is not a pull-request workflow run")

    authoritative_sibling = False
    for sibling in active_same_head_runs:
        sibling_id = _positive_int(sibling.get("id"))
        if sibling_id is None or sibling_id == candidate_id:
            continue
        if _positive_int(sibling.get("workflow_id")) != workflow_id:
            continue
        if not _run_identity_matches(
            sibling, repository=live_repo, branch=live_ref, head_sha=live_sha
        ):
            continue
        if sibling.get("status") == "in_progress" or sibling_id > candidate_id:
            authoritative_sibling = True
            break
    if not authoritative_sibling:
        raise CoalescingRefused("no distinct authoritative sibling remains active")


def _run_json(args: Sequence[str]) -> Any:
    """Run one bounded GitHub CLI call and decode its JSON response."""
    if not os.environ.get("GH_TOKEN"):
        raise RuntimeError("GH_TOKEN is required for current-head run coalescing")
    completed = subprocess.run(
        list(args),
        capture_output=True,
        text=True,
        check=False,
        shell=False,
        env=os.environ.copy(),
    )
    if completed.returncode != 0:
        diagnostic = (completed.stderr or completed.stdout or "GitHub API request failed").strip()
        raise RuntimeError(diagnostic[:600])
    return json.loads(completed.stdout or "null")


def _fetch_pr(repo: str, number: int) -> dict[str, Any]:
    """Fetch one live pull request through GitHub REST."""
    payload = _run_json(
        ["gh", "api", "-H", "Accept: application/vnd.github+json", f"repos/{repo}/pulls/{number}"]
    )
    if not isinstance(payload, dict):
        raise RuntimeError("GitHub returned malformed pull-request evidence")
    return payload


def _active_runs(repo: str, head_sha: str) -> list[dict[str, Any]]:
    """Fetch queued and in-progress runs for one exact commit SHA."""
    runs: list[dict[str, Any]] = []
    for status in ACTIVE_STATUSES:
        page = 1
        while True:
            payload = _run_json(
                [
                    "gh",
                    "api",
                    "--method",
                    "GET",
                    f"repos/{repo}/actions/runs",
                    "-f",
                    f"status={status}",
                    "-f",
                    f"head_sha={head_sha}",
                    "-F",
                    "per_page=100",
                    "-F",
                    f"page={page}",
                ]
            )
            if not isinstance(payload, dict) or not isinstance(payload.get("workflow_runs"), list):
                raise RuntimeError("GitHub returned malformed Actions run evidence")
            batch = payload["workflow_runs"]
            runs.extend(item for item in batch if isinstance(item, dict))
            if len(batch) < 100:
                break
            page += 1
    return runs


def _fetch_run(repo: str, run_id: int) -> dict[str, Any]:
    """Fetch one exact Actions run immediately before possible cancellation."""
    payload = _run_json(
        [
            "gh",
            "api",
            "-H",
            "Accept: application/vnd.github+json",
            f"repos/{repo}/actions/runs/{run_id}",
        ]
    )
    if not isinstance(payload, dict):
        raise RuntimeError("GitHub returned malformed Actions run identity evidence")
    return payload


def _cancel_run(repo: str, run_id: int) -> None:
    """Cancel one queued duplicate using GitHub's ordinary cancellation endpoint."""
    completed = subprocess.run(
        ["gh", "api", "-X", "POST", f"repos/{repo}/actions/runs/{run_id}/cancel"],
        capture_output=True,
        text=True,
        check=False,
        shell=False,
        env=os.environ.copy(),
    )
    if completed.returncode != 0:
        diagnostic = (completed.stderr or completed.stdout or "GitHub cancellation failed").strip()
        raise RuntimeError(diagnostic[:600])


def coalesce(repo: str, number: int, expected_repo: str, expected_ref: str, expected_head: str) -> list[int]:
    """Cancel redundant queued runs after exact live PR/run/sibling revalidation."""
    if not REPOSITORY_RE.fullmatch(repo) or not REPOSITORY_RE.fullmatch(expected_repo):
        raise RuntimeError("repository identity is malformed")
    if not GIT_SHA_RE.fullmatch(expected_head):
        raise RuntimeError("expected head must be a lowercase 40-character Git SHA")
    if number <= 0 or not expected_ref or any(char.isspace() for char in expected_ref):
        raise RuntimeError("pull-request identity is malformed")

    live_pr = _fetch_pr(repo, number)
    live_head = live_pr.get("head") or {}
    if (
        live_pr.get("state") != "open"
        or str(live_head.get("sha") or "").lower() != expected_head
        or live_head.get("ref") != expected_ref
        or ((live_head.get("repo") or {}).get("full_name") != expected_repo)
    ):
        raise CoalescingRefused("pull request head moved before duplicate classification")

    snapshot = _active_runs(repo, expected_head)
    candidates = select_duplicate_queued_run_ids(
        snapshot,
        repository=expected_repo,
        branch=expected_ref,
        head_sha=expected_head,
    )
    cancelled: list[int] = []
    for run_id in candidates:
        try:
            candidate = _fetch_run(repo, run_id)
            current_pr = _fetch_pr(repo, number)
            active = _active_runs(repo, expected_head)
            validate_candidate_against_live_state(
                candidate,
                live_pr=current_pr,
                active_same_head_runs=active,
            )
            _cancel_run(repo, run_id)
        except CoalescingRefused as exc:
            print(f"Preserving run {run_id}: {exc}")
            continue
        cancelled.append(run_id)
        print(f"Cancelled redundant queued current-head run {run_id} for {repo}#{number}.")
    return cancelled


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse the exact pull-request identity supplied by the trusted workflow."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--pr-number", required=True, type=int)
    parser.add_argument("--expected-head-repo", required=True)
    parser.add_argument("--expected-head-ref", required=True)
    parser.add_argument("--expected-head", required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the coalescer and fail closed on malformed or unavailable evidence."""
    args = parse_args(argv)
    coalesce(
        args.repo,
        args.pr_number,
        args.expected_head_repo,
        args.expected_head_ref,
        args.expected_head,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
