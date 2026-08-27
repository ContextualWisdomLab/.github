#!/usr/bin/env python3
"""Verify a quoted coverage conclusion against the canonical exact-head check."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


CANONICAL_CHECK_NAME = "coverage-evidence"
CANONICAL_WORKFLOW_NAMES = frozenset({"Required OpenCode Review"})
DISPATCH_WORKFLOW_NAME = "OpenCode Review Dispatch"
SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
REPO_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]*/[A-Za-z0-9_.-]+$")
TERMINAL_RESULTS = frozenset(
    {"success", "failure", "cancelled", "skipped", "neutral", "timed_out", "action_required"}
)
RETRY_DELAYS = (0.0, 1.0, 3.0)
TRANSIENT_GH_READ_ERROR_RE = re.compile(
    r"(?i)(?:http\s*(?:429|500|502|503|504)\b|rate.?limit|"
    r"secondary rate limit|timeout|timed out|temporar(?:y|ily) unavailable|"
    r"connection (?:reset|refused|closed)|tls handshake timeout)"
)

KAEFA_78_HEAD = "5092a70c9737221d6367e74643d06980609fe0b1"
KAEFA_75_HEAD = "4c8ad480a0f104601ca668cee5f0cf9372e819c3"
KAEFA_79_HEAD = "1c5d9f0491fc178be3f7f307dac521fbcbba6978"


class CoverageQuoteError(ValueError):
    """Raised when a review would quote a coverage result that is not canonical."""


def normalize_result(value: str) -> str:
    """Return a lowercase GitHub check conclusion or ``unknown``."""
    normalized = str(value or "").strip().casefold()
    if normalized in TERMINAL_RESULTS:
        return normalized
    return "unknown"


def check_head_sha(check: Mapping[str, Any]) -> str:
    """Return the commit SHA recorded on a check-run object."""
    head = check.get("head_sha") or check.get("headSha") or ""
    return str(head).strip()


def check_workflow_name(check: Mapping[str, Any]) -> str:
    """Return the workflow name that produced a check-run, if present.

    The REST list-check-runs response's ``check_suite`` object does not carry a
    ``workflow_run`` field, so this almost always returns "". ``app.name`` is
    always "GitHub Actions" for Actions-produced checks, not the workflow name,
    so it is not an acceptable fallback: a canonical exact-head check would be
    rejected by a workflow-name mismatch it can never satisfy. An empty result
    defers to ``is_canonical_coverage_check``'s ``not workflow`` acceptance.
    """
    suite = check.get("check_suite") or check.get("checkSuite") or {}
    if isinstance(suite, Mapping):
        run = suite.get("workflow_run") or suite.get("workflowRun") or {}
        if isinstance(run, Mapping):
            workflow = run.get("workflow") or {}
            if isinstance(workflow, Mapping):
                name = str(workflow.get("name") or "").strip()
                if name:
                    return name
    return ""


def check_run_id(check: Mapping[str, Any]) -> str:
    """Return the Actions run id recorded by a check-run, if available."""
    suite = check.get("check_suite") or check.get("checkSuite") or {}
    if isinstance(suite, Mapping):
        run = suite.get("workflow_run") or suite.get("workflowRun") or {}
        if isinstance(run, Mapping):
            value = str(run.get("id") or run.get("databaseId") or "").strip()
            if value.isdigit():
                return value
    details_url = str(check.get("details_url") or check.get("detailsUrl") or "").strip()
    match = re.search(r"/actions/runs/([0-9]+)(?:/|$)", details_url)
    return match.group(1) if match else ""


def is_canonical_coverage_check(
    check: Mapping[str, Any], head_sha: str, run_id: str | None = None
) -> bool:
    """Return whether a check-run is the exact-head canonical coverage-evidence check."""
    if str(check.get("name") or "").strip() != CANONICAL_CHECK_NAME:
        return False
    if check_head_sha(check).lower() != head_sha.lower():
        return False
    if run_id is not None and check_run_id(check) != str(run_id):
        return False
    status = str(check.get("status") or "").strip().casefold()
    if status and status != "completed":
        return False
    workflow = check_workflow_name(check)
    return not workflow or workflow in CANONICAL_WORKFLOW_NAMES



def terminal_dispatch_coverage_result(
    workflow_run: Mapping[str, Any],
    jobs: Sequence[Mapping[str, Any]],
    *,
    workflow_repo: str,
    target_repo: str,
    pr_number: str,
    head_sha: str,
    run_id: str,
) -> str:
    """Return coverage from the exact central repository_dispatch workflow job."""
    if not REPO_RE.fullmatch(workflow_repo):
        raise CoverageQuoteError("coverage identity requires a valid workflow repository")
    if not REPO_RE.fullmatch(target_repo):
        raise CoverageQuoteError("coverage identity requires a valid target repository")
    if not str(pr_number).isdigit() or int(pr_number) < 1:
        raise CoverageQuoteError("coverage identity requires a positive pull request number")
    if not SHA_RE.fullmatch(head_sha):
        raise CoverageQuoteError("coverage identity requires a 40-character head SHA")
    if not str(run_id).isdigit():
        raise CoverageQuoteError("coverage identity requires a numeric workflow run id")
    if str(workflow_run.get("id") or "") != str(run_id):
        raise CoverageQuoteError("coverage workflow run id does not match the current run")
    if str(workflow_run.get("event") or "") != "repository_dispatch":
        raise CoverageQuoteError("coverage workflow run is not repository_dispatch")
    if str(workflow_run.get("name") or "") != DISPATCH_WORKFLOW_NAME:
        raise CoverageQuoteError("coverage workflow name is not OpenCode Review Dispatch")
    repository = workflow_run.get("repository") or {}
    recorded_repo = (
        str(repository.get("full_name") or "").strip()
        if isinstance(repository, Mapping)
        else ""
    )
    if recorded_repo != workflow_repo:
        raise CoverageQuoteError("coverage workflow repository does not match")
    expected_title = (
        f"{DISPATCH_WORKFLOW_NAME} {target_repo}#{pr_number}@{head_sha}"
    )
    if str(workflow_run.get("display_title") or "").strip() != expected_title:
        raise CoverageQuoteError("coverage workflow target identity does not match")
    matches = [
        job
        for job in jobs
        if isinstance(job, Mapping)
        and str(job.get("name") or "").strip() == CANONICAL_CHECK_NAME
        and str(job.get("status") or "").strip().casefold() == "completed"
    ]
    if len(matches) != 1:
        raise CoverageQuoteError(
            f"expected one completed {CANONICAL_CHECK_NAME} job in current run"
        )
    result = normalize_result(str(matches[0].get("conclusion") or ""))
    if result == "unknown":
        raise CoverageQuoteError(
            f"current-run {CANONICAL_CHECK_NAME} conclusion is missing or non-terminal"
        )
    return result

def terminal_coverage_result(
    check_runs: Sequence[Mapping[str, Any]],
    head_sha: str,
    run_id: str | None = None,
) -> str:
    """Return the terminal canonical coverage-evidence conclusion for ``head_sha``."""
    if not SHA_RE.fullmatch(head_sha):
        raise CoverageQuoteError("coverage identity requires a 40-character head SHA")
    if run_id is not None and not str(run_id).isdigit():
        raise CoverageQuoteError("coverage identity requires a numeric workflow run id")
    matches = [
        check
        for check in check_runs
        if isinstance(check, Mapping)
        and is_canonical_coverage_check(check, head_sha, run_id)
    ]
    if not matches:
        raise CoverageQuoteError(
            f"no completed canonical {CANONICAL_CHECK_NAME} check for head {head_sha}"
        )
    preferred = [
        check
        for check in matches
        if check_workflow_name(check) in CANONICAL_WORKFLOW_NAMES
    ]
    chosen = preferred[-1] if preferred else matches[-1]
    result = normalize_result(str(chosen.get("conclusion") or ""))
    if result == "unknown":
        raise CoverageQuoteError(
            f"canonical {CANONICAL_CHECK_NAME} conclusion is missing or non-terminal"
        )
    return result


def assert_quoted_matches(
    quoted_result: str,
    check_runs: Sequence[Mapping[str, Any]],
    head_sha: str,
    run_id: str | None = None,
) -> str:
    """Return the canonical result or raise when the quoted conclusion differs."""
    canonical = terminal_coverage_result(check_runs, head_sha, run_id)
    quoted = normalize_result(quoted_result)
    if quoted != canonical:
        raise CoverageQuoteError(
            f"quoted coverage-evidence result {quoted!r} does not match "
            f"canonical exact-head result {canonical!r} for {head_sha}"
        )
    return canonical


def load_check_runs(path: str | None) -> list[Mapping[str, Any]]:
    """Load check-run objects from a JSON file or stdin."""
    raw = sys.stdin.read() if not path or path == "-" else Path(path).read_text(encoding="utf-8")
    loaded = json.loads(raw)
    if isinstance(loaded, Mapping) and isinstance(loaded.get("check_runs"), list):
        loaded = loaded["check_runs"]
    if not isinstance(loaded, list):
        raise CoverageQuoteError("coverage identity payload must be a check-run array")
    return [item for item in loaded if isinstance(item, Mapping)]


def fetch_check_runs(repo: str, head_sha: str) -> list[Mapping[str, Any]]:
    """Read exact-head check-runs through gh without invoking a shell."""
    if not REPO_RE.fullmatch(repo):
        raise CoverageQuoteError(f"coverage identity requires an owner/repo value, got {repo!r}")
    if not SHA_RE.fullmatch(head_sha):
        raise CoverageQuoteError("coverage identity requires a 40-character head SHA")
    completed = None
    for attempt, delay in enumerate(RETRY_DELAYS):
        if delay:
            time.sleep(delay)
        completed = subprocess.run(
            [
                "gh",
                "api",
                f"repos/{repo}/commits/{head_sha}/check-runs?per_page=100",
                "--paginate",
                "--slurp",
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            shell=False,
        )
        if completed.returncode == 0:
            break
        detail = (
            completed.stderr or completed.stdout or "gh check-runs lookup failed"
        ).strip()
        if (
            not TRANSIENT_GH_READ_ERROR_RE.search(detail)
            or attempt + 1 >= len(RETRY_DELAYS)
        ):
            raise CoverageQuoteError(
                f"canonical coverage check lookup failed: {detail}"
            )
    if completed is None or completed.returncode != 0:
        raise CoverageQuoteError("canonical coverage check lookup failed after retries")
    loaded = json.loads(completed.stdout or "{}")
    if isinstance(loaded, list):
        runs: list[Mapping[str, Any]] = []
        for page in loaded:
            if isinstance(page, Mapping) and isinstance(page.get("check_runs"), list):
                runs.extend(
                    item for item in page["check_runs"] if isinstance(item, Mapping)
                )
            elif isinstance(page, Mapping):
                runs.append(page)
        return runs
    if isinstance(loaded, Mapping) and isinstance(loaded.get("check_runs"), list):
        return [item for item in loaded["check_runs"] if isinstance(item, Mapping)]
    raise CoverageQuoteError("canonical coverage check lookup returned malformed JSON")



def _run_gh_json(args: list[str]) -> Any:
    """Run one bounded authenticated GitHub JSON read."""
    completed = None
    for attempt, delay in enumerate(RETRY_DELAYS):
        if delay:
            time.sleep(delay)
        completed = subprocess.run(
            args,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            shell=False,
        )
        if completed.returncode == 0:
            break
        detail = (
            completed.stderr or completed.stdout or "gh workflow lookup failed"
        ).strip()
        if (
            not TRANSIENT_GH_READ_ERROR_RE.search(detail)
            or attempt + 1 >= len(RETRY_DELAYS)
        ):
            raise CoverageQuoteError(f"canonical workflow lookup failed: {detail}")
    if completed is None or completed.returncode != 0:
        raise CoverageQuoteError("canonical workflow lookup failed after retries")
    return json.loads(completed.stdout or "{}")


def fetch_dispatch_workflow_run(workflow_repo: str, run_id: str) -> Mapping[str, Any]:
    """Read the exact central workflow-run metadata."""
    if not REPO_RE.fullmatch(workflow_repo):
        raise CoverageQuoteError("coverage identity requires a valid workflow repository")
    if not str(run_id).isdigit():
        raise CoverageQuoteError("coverage identity requires a numeric workflow run id")
    loaded = _run_gh_json(
        ["gh", "api", f"repos/{workflow_repo}/actions/runs/{run_id}"]
    )
    if not isinstance(loaded, Mapping):
        raise CoverageQuoteError("canonical workflow run lookup returned malformed JSON")
    return loaded


def fetch_dispatch_workflow_jobs(
    workflow_repo: str, run_id: str
) -> list[Mapping[str, Any]]:
    """Read latest-attempt jobs from the exact central workflow run."""
    if not REPO_RE.fullmatch(workflow_repo):
        raise CoverageQuoteError("coverage identity requires a valid workflow repository")
    if not str(run_id).isdigit():
        raise CoverageQuoteError("coverage identity requires a numeric workflow run id")
    loaded = _run_gh_json(
        [
            "gh",
            "api",
            f"repos/{workflow_repo}/actions/runs/{run_id}/jobs?filter=latest&per_page=100",
            "--paginate",
            "--slurp",
        ]
    )
    pages = loaded if isinstance(loaded, list) else [loaded]
    jobs: list[Mapping[str, Any]] = []
    for page in pages:
        if not isinstance(page, Mapping) or not isinstance(page.get("jobs"), list):
            raise CoverageQuoteError("canonical workflow jobs lookup returned malformed JSON")
        jobs.extend(job for job in page["jobs"] if isinstance(job, Mapping))
    return jobs

def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse coverage-identity CLI arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default="")
    parser.add_argument("--workflow-repo", default="")
    parser.add_argument("--pr-number", default="")
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--run-id")
    parser.add_argument("--quoted-result", required=True)
    parser.add_argument("--check-runs-file")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Verify a quoted coverage conclusion and print the canonical result."""
    args = parse_args(argv)
    try:
        if args.check_runs_file:
            checks = load_check_runs(args.check_runs_file)
            canonical = assert_quoted_matches(
                args.quoted_result, checks, args.head_sha, args.run_id
            )
        elif args.workflow_repo:
            if not args.repo or not args.pr_number or not args.run_id:
                raise CoverageQuoteError(
                    "dispatch coverage identity needs target repo, PR number, and run id"
                )
            workflow_run = fetch_dispatch_workflow_run(
                args.workflow_repo, args.run_id
            )
            jobs = fetch_dispatch_workflow_jobs(args.workflow_repo, args.run_id)
            canonical = terminal_dispatch_coverage_result(
                workflow_run,
                jobs,
                workflow_repo=args.workflow_repo,
                target_repo=args.repo,
                pr_number=args.pr_number,
                head_sha=args.head_sha,
                run_id=args.run_id,
            )
            quoted = normalize_result(args.quoted_result)
            if quoted != canonical:
                raise CoverageQuoteError(
                    f"quoted coverage-evidence result {quoted!r} does not match "
                    f"canonical current-run result {canonical!r} for {args.head_sha}"
                )
        elif args.repo:
            checks = fetch_check_runs(args.repo, args.head_sha)
            canonical = assert_quoted_matches(
                args.quoted_result, checks, args.head_sha, args.run_id
            )
        else:
            raise CoverageQuoteError("coverage identity needs --repo or --check-runs-file")
    except (CoverageQuoteError, json.JSONDecodeError, OSError) as exc:
        print(f"::error::{exc}", file=sys.stderr)
        summary = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary:
            with open(summary, "a", encoding="utf-8") as handle:
                handle.write("## Coverage identity failure\n\n")
                handle.write(f"{exc}\n")
        return 1
    sys.stdout.write(f"{canonical}\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
