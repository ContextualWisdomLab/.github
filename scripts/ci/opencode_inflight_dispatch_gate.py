#!/usr/bin/env python3
"""Detect an in-flight same-head OpenCode Review Dispatch before re-dispatching.

The required OpenCode entrypoint (`opencode-review.yml`) historically posted a
fresh ``repository_dispatch`` whenever a formal receipt was missing, then
fail-closed until wake. Under org queue saturation that handshake is correct
(no success without verdict), but duplicate same-head dispatches amplified the
queue and could replace pending owners. The central workflow now serializes
same-head owners with ``queue: max`` on a repository/PR/head group, while its
downstream repository/PR review group retains ``cancel-in-progress: true`` so a
new head can retire stale semantic work (pg-erd-cloud#1183 run 35412595263 /
appguardrail#1247).

This helper mirrors the scheduler's ``already_running`` title match against
central ``ContextualWisdomLab/.github`` ``repository_dispatch`` runs so the
required path skips a second dispatch when one exact-head review is already
queued or running. It never treats in-flight work as a green verdict.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections.abc import Mapping, Sequence
from typing import Any

SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
REPO_RE = re.compile(
    r"^[A-Za-z0-9_][A-Za-z0-9_.-]*/(?:\.github|[A-Za-z0-9_][A-Za-z0-9_.-]*)$"
)
PR_NUMBER_RE = re.compile(r"^[1-9][0-9]*$")
CENTRAL_DISPATCH_REPO = "ContextualWisdomLab/.github"
OPENCODE_DISPATCH_TITLE = "OpenCode Review Dispatch"
OPENCODE_DISPATCH_WORKFLOW = "opencode-review-dispatch.yml"
# GitHub REST's complete nonterminal workflow-run status set. Listing every
# member prevents a duplicate dispatch from cancelling a run that is admitted
# but has not yet reached the queued or in-progress states.
DEFAULT_STATUSES: tuple[str, ...] = (
    "queued",
    "in_progress",
    "requested",
    "waiting",
    "pending",
)


class InFlightDispatchError(ValueError):
    """Raised when in-flight dispatch inputs are malformed."""


def dispatch_run_title(target_repository: str, pr_number: int, head_sha: str) -> str:
    """Return the exact ``run-name`` / display_title prefix for one head."""
    return f"{OPENCODE_DISPATCH_TITLE} {target_repository}#{pr_number}@{head_sha}"


def validate_inputs(
    target_repository: str, pr_number: str, head_sha: str
) -> tuple[str, int, str]:
    """Fail closed on non-canonical repository, PR number, or head SHA."""
    repo = target_repository.strip()
    number = pr_number.strip()
    sha = head_sha.strip()
    components = repo.split("/")
    if not REPO_RE.fullmatch(repo) or any(
        ".." in component or component.endswith(".") for component in components
    ):
        raise InFlightDispatchError(f"invalid target repository: {target_repository!r}")
    if not PR_NUMBER_RE.fullmatch(number):
        raise InFlightDispatchError(f"invalid pull request number: {pr_number!r}")
    if not SHA_RE.fullmatch(sha):
        raise InFlightDispatchError(f"invalid head SHA: {head_sha!r}")
    return repo, int(number), sha.lower()


def _gh_api_json(args: Sequence[str], *, token: str) -> Any:
    """Run ``gh api`` and parse JSON, surfacing stderr on failure."""
    env = os.environ.copy()
    env["GH_TOKEN"] = token
    completed = subprocess.run(
        ["gh", "api", *args],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise InFlightDispatchError(
            f"gh api {' '.join(args)} failed ({completed.returncode}): {detail[:500]}"
        )
    try:
        return json.loads(completed.stdout or "null")
    except json.JSONDecodeError as exc:
        raise InFlightDispatchError(f"gh api returned non-JSON: {exc}") from exc


def list_repository_dispatch_runs(
    *,
    token: str,
    status: str,
    per_page: int = 100,
) -> list[Mapping[str, Any]]:
    """Return every canonical OpenCode repository_dispatch run for one status."""
    payload = _gh_api_json(
        [
            "--paginate",
            "--slurp",
            f"repos/{CENTRAL_DISPATCH_REPO}/actions/workflows/"
            f"{OPENCODE_DISPATCH_WORKFLOW}/runs"
            f"?event=repository_dispatch&status={status}&per_page={per_page}",
        ],
        token=token,
    )
    pages = [payload] if isinstance(payload, Mapping) else payload
    if not isinstance(pages, list) or not pages or any(
        not isinstance(page, Mapping) for page in pages
    ):
        raise InFlightDispatchError("actions/runs payload was not an object or page list")
    result: list[Mapping[str, Any]] = []
    for page in pages:
        runs = page.get("workflow_runs")
        if not isinstance(runs, list):
            raise InFlightDispatchError(
                "actions/runs page did not contain a workflow_runs list"
            )
        result.extend(run for run in runs if isinstance(run, Mapping))
    return result


def matching_inflight_runs(
    runs: Sequence[Mapping[str, Any]],
    *,
    target_repository: str,
    pr_number: int,
    head_sha: str,
) -> list[Mapping[str, Any]]:
    """Select runs whose display title exactly identifies the target head."""
    expected = dispatch_run_title(target_repository, pr_number, head_sha).casefold()
    matched: list[Mapping[str, Any]] = []
    for run in runs:
        title = str(run.get("display_title") or run.get("name") or "").strip()
        if title.casefold() == expected:
            matched.append(run)
    return matched


def matching_target_runs(
    runs: Sequence[Mapping[str, Any]],
    *,
    target_repository: str,
    pr_number: int,
) -> list[Mapping[str, Any]]:
    """Select canonical-workflow runs for any head of one pull request."""
    prefix = (
        f"{OPENCODE_DISPATCH_TITLE} {target_repository}#{pr_number}@".casefold()
    )
    matched: list[Mapping[str, Any]] = []
    for run in runs:
        title = str(run.get("display_title") or "").strip().casefold()
        if title.startswith(prefix) and SHA_RE.fullmatch(title[len(prefix) :]):
            matched.append(run)
    return matched


def evaluate_inflight(
    *,
    target_repository: str,
    pr_number: str,
    head_sha: str,
    token: str,
    statuses: Sequence[str] = DEFAULT_STATUSES,
) -> tuple[str, list[str]]:
    """Return ``present``/``missing`` and matching central run ids."""
    repo, number, sha = validate_inputs(target_repository, pr_number, head_sha)
    exact_ids: list[str] = []
    target_ids: list[str] = []
    for status in statuses:
        runs = list_repository_dispatch_runs(token=token, status=status)
        exact = matching_inflight_runs(
            runs,
            target_repository=repo,
            pr_number=number,
            head_sha=sha,
        )
        target = matching_target_runs(
            runs,
            target_repository=repo,
            pr_number=number,
        )
        exact_ids.extend(
            str(run["id"]) for run in exact if run.get("id") is not None
        )
        target_ids.extend(
            str(run["id"]) for run in target if run.get("id") is not None
        )
    if exact_ids:
        return "present", exact_ids
    if target_ids:
        return "stale", target_ids
    return "missing", []


def main(argv: Sequence[str] | None = None) -> int:
    """CLI: print ``present``, ``stale``, or ``missing`` dispatch state."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-repository", required=True)
    parser.add_argument("--pr-number", required=True)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument(
        "--token-env",
        default="GH_TOKEN",
        help="Environment variable holding the GitHub token (default: GH_TOKEN)",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    token = os.environ.get(args.token_env) or os.environ.get("GITHUB_TOKEN") or ""
    if not token.strip():
        print(
            f"::error::OpenCode in-flight dispatch gate requires {args.token_env}.",
            file=sys.stderr,
        )
        return 2
    try:
        state, run_ids = evaluate_inflight(
            target_repository=args.target_repository,
            pr_number=args.pr_number,
            head_sha=args.head_sha,
            token=token,
        )
    except InFlightDispatchError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 2
    if run_ids:
        subject = "Same-head" if state == "present" else "Prior-head"
        print(
            f"{subject} OpenCode Review Dispatch already in flight: "
            + ", ".join(run_ids),
            file=sys.stderr,
        )
    print(state)
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through ``main`` tests
    raise SystemExit(main())
