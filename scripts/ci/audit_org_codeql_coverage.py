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
import json
from pathlib import Path
import sys
from typing import Any, TextIO


def audit_codeql_coverage(repositories: list[dict[str, Any]]) -> list[str]:
    """Return one human-readable error per repository with zero CodeQL coverage.

    A repository is flagged only when it is not archived AND both coverage
    signals are absent: ``default_setup_state`` is not ``"configured"`` and
    ``has_recent_codeql_analysis`` is not ``True``. Archived repositories are
    skipped entirely -- they cannot run workflows or code scanning, so a lack
    of coverage there is not a real product gap (matching the exclusion of
    ``trivy-sarif-repro`` from today's manual remediation).
    """
    errors: list[str] = []
    for repository in repositories:
        if repository.get("archived"):
            continue
        name = repository.get("name")
        has_default_setup = repository.get("default_setup_state") == "configured"
        has_recent_analysis = repository.get("has_recent_codeql_analysis") is True
        if not has_default_setup and not has_recent_analysis:
            errors.append(
                f"{name} has no CodeQL coverage from any source "
                "(no default-setup, no recent analysis)"
            )
    return errors


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
