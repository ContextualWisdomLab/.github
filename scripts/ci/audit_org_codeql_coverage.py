#!/usr/bin/env python3
"""Audit every ContextualWisdomLab organization repository for real CodeQL coverage.

This is a permanent, read-only, scheduled counterpart to the one-time manual
remediation performed on 2026-09-03: 23 organization repositories had zero
CodeQL coverage from any source (no repository-local workflow, no GitHub
native ``code-scanning/default-setup``) and were fixed by hand. This script
detects that same gap automatically going forward -- e.g. a newly created
repository, or an existing repository whose default-setup is disabled -- so
the gap cannot silently recur. It only reports drift; it never mutates
anything. Remediation (enabling default-setup, or adding a workflow) is a
separate, human/agent-directed action.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
from typing import Any, TextIO


# Live-verified (2026-09-03) via `gh api
# repos/ContextualWisdomLab/wardnet/code-scanning/default-setup --jq
# '.schedule'` -> "weekly": GitHub's native code-scanning/default-setup --
# the mechanism most organization repositories rely on for CodeQL coverage,
# as opposed to a locally-triggered push/pull_request workflow, which would
# produce analysis records far more often than weekly and never approach
# this threshold in practice -- runs on a 7-day cadence. A repository
# relying on default-setup will therefore realistically go up to ~7 days
# between analyses in the normal case.
#
# 35 days is deliberately 5x that observed 7-day interval: a safety margin
# against a single missed or delayed scheduled run (a holiday, a GitHub
# platform incident, or this organization's own well-documented Actions
# queue congestion under hosted-runner saturation -- see
# docs/doctoring/actions-queue-saturation-hourly-sweep.md, a real, observed
# risk here, not hypothetical), not an unexplained rule of thumb.
CODEQL_ANALYSIS_FRESHNESS_DAYS = 35


def _is_analysis_fresh_and_successful(
    latest_codeql_analysis: Any, now: datetime
) -> bool:
    """Return True when ``latest_codeql_analysis`` is recent and error-free.

    A malformed or unparseable ``created_at`` -- or a missing/non-dict record
    -- fails closed (returns False) rather than raising, so one bad record
    cannot crash the whole audit run.
    """
    if not isinstance(latest_codeql_analysis, dict):
        return False
    if latest_codeql_analysis.get("error"):
        return False
    created_at = latest_codeql_analysis.get("created_at")
    if not isinstance(created_at, str):
        return False
    try:
        parsed = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError:
        return False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed >= now - timedelta(days=CODEQL_ANALYSIS_FRESHNESS_DAYS)


def repositories_without_codeql(
    repositories: list[dict[str, Any]], now: datetime | None = None
) -> list[dict[str, Any]]:
    """Return non-archived repositories without current CodeQL coverage.

    A repository is flagged only when it is not archived AND both coverage
    signals are absent: ``default_setup_state`` is not ``"configured"``, and
    ``latest_codeql_analysis`` is not a fresh (within
    ``CODEQL_ANALYSIS_FRESHNESS_DAYS``), error-free analysis record. Archived
    repositories are skipped entirely -- they cannot run workflows or code
    scanning, so a lack of coverage there is not a real product gap (matching
    the exclusion of ``trivy-sarif-repro`` from today's manual remediation).
    """
    current = now or datetime.now(timezone.utc)
    uncovered: list[dict[str, Any]] = []
    for repository in repositories:
        if repository.get("archived"):
            continue
        # "configured" is GitHub's own forward-looking commitment to run
        # CodeQL going forward (like a scheduled cron guarantee), not a
        # one-time historical scan that can go stale -- so it does not need
        # the same freshness check as latest_codeql_analysis below. Do not
        # "fix" this into requiring a completed scan.
        has_default_setup = repository.get("default_setup_state") == "configured"
        has_fresh_analysis = _is_analysis_fresh_and_successful(
            repository.get("latest_codeql_analysis"), current
        )
        if not has_default_setup and not has_fresh_analysis:
            uncovered.append(repository)
    return uncovered


def audit_codeql_coverage(
    repositories: list[dict[str, Any]], now: datetime | None = None
) -> list[str]:
    """Return one human-readable error per repository with zero CodeQL coverage."""
    return [
        f"{repository.get('name')} has no CodeQL coverage from any source "
        "(no default-setup, no recent analysis)"
        for repository in repositories_without_codeql(repositories, now)
    ]


def load_payload(path: Path | None, stdin: TextIO) -> list[dict[str, Any]]:
    """Load the per-repository JSON array from ``path`` or standard input."""
    if path is None:
        payload = json.load(stdin)
    else:
        with path.open(encoding="utf-8") as handle:
            payload = json.load(handle)
    if not isinstance(payload, list):
        raise ValueError("repository JSON root must be a list")
    return payload


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse the optional repository JSON array path."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repositories_json", nargs="?", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Audit the organization's CodeQL coverage and print every gap found."""
    args = parse_args(argv)
    try:
        repositories = load_payload(args.repositories_json, sys.stdin)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: unable to load repository JSON: {exc}", file=sys.stderr)
        return 2

    errors = audit_codeql_coverage(repositories)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        print(
            f"FAIL: {len(errors)} repositories have no CodeQL coverage",
            file=sys.stderr,
        )
        return 1

    print(f"PASS: all {len(repositories)} repositories have real CodeQL coverage")
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through main()
    raise SystemExit(main())
