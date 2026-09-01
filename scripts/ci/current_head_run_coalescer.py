#!/usr/bin/env python3
"""Retire redundant queued GitHub Actions runs for one exact open PR head.

The coalescer is intentionally narrower than ordinary stale-head cleanup. It
never intentionally cancels an in-progress run and never cancels the only
queued run for a workflow. A queued candidate is eligible only when a distinct
same-workflow run is still authoritative after live PR, association, sibling,
and candidate state are re-fetched immediately before cancellation.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from typing import Any, Iterable, Mapping, Sequence


GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
REPOSITORY_RE = re.compile(
    r"^(?!\.{1,2}/)[A-Za-z0-9_.-]+/(?!\.{1,2}$)[A-Za-z0-9_.-]+$"
)
PR_EVENTS = frozenset({"pull_request", "pull_request_target"})
ACTIVE_STATUSES = ("queued", "in_progress")
API_TIMEOUT_SECONDS = 30


class CoalescingRefused(RuntimeError):
    """Signal that live evidence is insufficient for a destructive cancellation."""


def _positive_int(value: object) -> int | None:
    """Return a positive integer without accepting booleans or numeric strings."""
    return value if type(value) is int and value > 0 else None


def _pull_request_associations(run_data: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return only well-shaped pull-request associations from an Actions run."""
    value = run_data.get("pull_requests")
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _association_number(association: Mapping[str, Any]) -> int | None:
    """Return one associated PR number when GitHub supplied a positive integer."""
    return _positive_int(association.get("number"))


def _head_tuple(value: Mapping[str, Any]) -> tuple[str, str, str]:
    """Normalize a PR-style head object to repository, ref, and lowercase SHA."""
    repository = ((value.get("repo") or {}).get("full_name") or "")
    ref = str(value.get("ref") or "")
    sha = str(value.get("sha") or "").lower()
    return repository, ref, sha


def _base_tuple(value: Mapping[str, Any]) -> tuple[str, str, str]:
    """Normalize a PR-style base object to repository, ref, and lowercase SHA."""
    repository = ((value.get("repo") or {}).get("full_name") or "")
    ref = str(value.get("ref") or "")
    sha = str(value.get("sha") or "").lower()
    return repository, ref, sha


def _run_matches_head_identity(
    run_data: Mapping[str, Any], *, repository: str, branch: str, head_sha: str
) -> bool:
    """Match a run to the live PR head, including pull_request_target semantics."""
    event = run_data.get("event")
    if event not in PR_EVENTS:
        return False
    if event == "pull_request":
        if (
            str(run_data.get("head_sha") or "").lower() == head_sha
            and run_data.get("head_branch") == branch
            and ((run_data.get("head_repository") or {}).get("full_name") == repository)
        ):
            return True
    for association in _pull_request_associations(run_data):
        if _head_tuple(association.get("head") or {}) == (repository, branch, head_sha):
            return True
    return False


def _run_identity_matches(
    run_data: dict[str, Any],
    *,
    repository: str,
    branch: str,
    head_sha: str,
) -> bool:
    """Return whether one run belongs to the exact PR-head cancellation boundary."""
    return (
        _run_matches_head_identity(
            run_data, repository=repository, branch=branch, head_sha=head_sha
        )
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
    """Select redundant queued runs while retaining one authoritative sibling."""
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


def _run_pr_scope_is_safe(
    run_data: Mapping[str, Any],
    *,
    live_pr: Mapping[str, Any],
    current_pr_number: int,
    associated_prs: Mapping[int, Mapping[str, Any]],
) -> bool:
    """Keep evidence isolated across live PRs while allowing exact closed predecessors."""
    associations = _pull_request_associations(run_data)
    if not associations:
        return False
    live_head = _head_tuple(live_pr.get("head") or {})
    live_base = _base_tuple(live_pr.get("base") or {})
    if not all(live_head) or not all(live_base) or not GIT_SHA_RE.fullmatch(live_base[2]):
        return False
    saw_current = False
    saw_closed_predecessor = False
    for association in associations:
        number = _association_number(association)
        if number is None:
            return False
        if _head_tuple(association.get("head") or {}) != live_head:
            return False
        if _base_tuple(association.get("base") or {}) != live_base:
            return False
        if number == current_pr_number:
            saw_current = True
            continue
        other = associated_prs.get(number)
        if not isinstance(other, Mapping):
            return False
        if other.get("state") == "open":
            return False
        if _head_tuple(other.get("head") or {}) != live_head:
            return False
        if _base_tuple(other.get("base") or {}) != live_base:
            return False
        saw_closed_predecessor = True
    return saw_current or saw_closed_predecessor


def validate_candidate_against_live_state(
    candidate: dict[str, Any],
    *,
    live_pr: dict[str, Any],
    active_same_head_runs: Sequence[dict[str, Any]],
    current_pr_number: int | None = None,
    associated_prs: Mapping[int, Mapping[str, Any]] | None = None,
) -> None:
    """Fail closed unless a queued candidate still has an authoritative sibling."""
    if candidate.get("status") != "queued":
        raise CoalescingRefused("candidate is no longer queued")
    if live_pr.get("state") != "open":
        raise CoalescingRefused("pull request is no longer open")

    live_repo, live_ref, live_sha = _head_tuple(live_pr.get("head") or {})
    if (
        not GIT_SHA_RE.fullmatch(live_sha)
        or not _run_matches_head_identity(
            candidate, repository=live_repo, branch=live_ref, head_sha=live_sha
        )
    ):
        raise CoalescingRefused("pull request head moved after duplicate classification")

    candidate_id = _positive_int(candidate.get("id"))
    workflow_id = _positive_int(candidate.get("workflow_id"))
    if candidate_id is None or workflow_id is None:
        raise CoalescingRefused("candidate identity is malformed")
    if candidate.get("event") not in PR_EVENTS:
        raise CoalescingRefused("candidate is not a pull-request workflow run")

    association_map = associated_prs or {}
    if current_pr_number is not None and not _run_pr_scope_is_safe(
        candidate,
        live_pr=live_pr,
        current_pr_number=current_pr_number,
        associated_prs=association_map,
    ):
        raise CoalescingRefused("candidate belongs to an independent pull request")

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
        if current_pr_number is not None and not _run_pr_scope_is_safe(
            sibling,
            live_pr=live_pr,
            current_pr_number=current_pr_number,
            associated_prs=association_map,
        ):
            continue
        if sibling.get("status") == "in_progress" or sibling_id > candidate_id:
            authoritative_sibling = True
            break
    if not authoritative_sibling:
        raise CoalescingRefused("no distinct authoritative sibling remains active")


def _run_json(args: Sequence[str]) -> Any:
    """Run one token-bound GitHub CLI call with an individual request timeout."""
    if not os.environ.get("GH_TOKEN"):
        raise RuntimeError("GH_TOKEN is required for current-head run coalescing")
    try:
        completed = subprocess.run(
            list(args),
            capture_output=True,
            text=True,
            check=False,
            shell=False,
            env=os.environ.copy(),
            timeout=API_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("GitHub API request timed out") from exc
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


def _active_runs(repo: str, _head_sha: str) -> list[dict[str, Any]]:
    """Fetch all queued/in-progress runs so pull_request_target runs are visible."""
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
    """Request ordinary cancellation using the same explicit token/timeout contract."""
    _run_json(["gh", "api", "-X", "POST", f"repos/{repo}/actions/runs/{run_id}/cancel"])


def _associated_prs(
    repo: str,
    runs: Sequence[Mapping[str, Any]],
    current_pr_number: int,
    *,
    repository: str,
    branch: str,
    head_sha: str,
) -> dict[int, dict[str, Any]]:
    """Fetch only same-head non-current PR associations needed for predecessor proof."""
    numbers = {
        number
        for run_data in runs
        if _run_matches_head_identity(
            run_data, repository=repository, branch=branch, head_sha=head_sha
        )
        for association in _pull_request_associations(run_data)
        if (number := _association_number(association)) is not None
        and number != current_pr_number
    }
    return {number: _fetch_pr(repo, number) for number in sorted(numbers)}


def coalesce(repo: str, number: int, expected_repo: str, expected_ref: str, expected_head: str) -> list[int]:
    """Cancel redundant queued runs after exact live PR/run/sibling revalidation."""
    if not REPOSITORY_RE.fullmatch(repo) or not REPOSITORY_RE.fullmatch(expected_repo):
        raise RuntimeError("repository identity is malformed")
    if not GIT_SHA_RE.fullmatch(expected_head):
        raise RuntimeError("expected head must be a lowercase 40-character Git SHA")
    if number <= 0 or not expected_ref or any(char.isspace() for char in expected_ref):
        raise RuntimeError("pull-request identity is malformed")

    live_pr = _fetch_pr(repo, number)
    live_repo, live_ref, live_sha = _head_tuple(live_pr.get("head") or {})
    if (
        live_pr.get("state") != "open"
        or live_sha != expected_head
        or live_ref != expected_ref
        or live_repo != expected_repo
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
            current_pr = _fetch_pr(repo, number)
            active = _active_runs(repo, expected_head)
            association_map = _associated_prs(
                repo,
                active,
                number,
                repository=expected_repo,
                branch=expected_ref,
                head_sha=expected_head,
            )
            current_pr = _fetch_pr(repo, number)
            candidate = _fetch_run(repo, run_id)
            validate_candidate_against_live_state(
                candidate,
                live_pr=current_pr,
                active_same_head_runs=active,
                current_pr_number=number,
                associated_prs=association_map,
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
