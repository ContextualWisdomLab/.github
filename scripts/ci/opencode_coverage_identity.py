#!/usr/bin/env python3
"""Verify a quoted coverage conclusion against the canonical exact-head check."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


CANONICAL_CHECK_NAME = "coverage-evidence"
CANONICAL_WORKFLOW_NAMES = frozenset({"Required OpenCode Review"})
SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
TERMINAL_RESULTS = frozenset(
    {"success", "failure", "cancelled", "skipped", "neutral", "timed_out", "action_required"}
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
    """Return the workflow name that produced a check-run, if present."""
    suite = check.get("check_suite") or check.get("checkSuite") or {}
    if isinstance(suite, Mapping):
        run = suite.get("workflow_run") or suite.get("workflowRun") or {}
        if isinstance(run, Mapping):
            workflow = run.get("workflow") or {}
            if isinstance(workflow, Mapping):
                name = str(workflow.get("name") or "").strip()
                if name:
                    return name
    app = check.get("app") or {}
    if isinstance(app, Mapping):
        return str(app.get("name") or "").strip()
    return ""


def is_canonical_coverage_check(check: Mapping[str, Any], head_sha: str) -> bool:
    """Return whether a check-run is the exact-head canonical coverage-evidence check."""
    if str(check.get("name") or "").strip() != CANONICAL_CHECK_NAME:
        return False
    if check_head_sha(check).lower() != head_sha.lower():
        return False
    status = str(check.get("status") or "").strip().casefold()
    if status and status != "completed":
        return False
    workflow = check_workflow_name(check)
    return not workflow or workflow in CANONICAL_WORKFLOW_NAMES


def terminal_coverage_result(
    check_runs: Sequence[Mapping[str, Any]], head_sha: str
) -> str:
    """Return the terminal canonical coverage-evidence conclusion for ``head_sha``."""
    if not SHA_RE.fullmatch(head_sha):
        raise CoverageQuoteError("coverage identity requires a 40-character head SHA")
    matches = [
        check
        for check in check_runs
        if isinstance(check, Mapping) and is_canonical_coverage_check(check, head_sha)
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
    quoted_result: str, check_runs: Sequence[Mapping[str, Any]], head_sha: str
) -> str:
    """Return the canonical result or raise when the quoted conclusion differs."""
    canonical = terminal_coverage_result(check_runs, head_sha)
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
    completed = subprocess.run(
        [
            "gh",
            "api",
            f"repos/{repo}/commits/{head_sha}/check-runs?per_page=100",
            "--paginate",
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        shell=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "gh check-runs lookup failed").strip()
        raise CoverageQuoteError(f"canonical coverage check lookup failed: {detail}")
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


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse coverage-identity CLI arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default="")
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--quoted-result", required=True)
    parser.add_argument("--check-runs-file")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Verify a quoted coverage conclusion and print the canonical result."""
    args = parse_args(argv)
    try:
        if args.check_runs_file:
            checks = load_check_runs(args.check_runs_file)
        elif args.repo:
            checks = fetch_check_runs(args.repo, args.head_sha)
        else:
            raise CoverageQuoteError("coverage identity needs --repo or --check-runs-file")
        canonical = assert_quoted_matches(args.quoted_result, checks, args.head_sha)
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
