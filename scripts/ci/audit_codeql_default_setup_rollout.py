#!/usr/bin/env python3
"""Classify CodeQL default-setup removal snapshots without mutating GitHub."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, TextIO

EXEMPT_REPOSITORIES = frozenset({".github", "noema", "IRT-bibliography-set"})
SUCCESS = frozenset({"success", "neutral", "skipped"})
PENDING = frozenset({"queued", "in_progress", "pending", "requested", "waiting"})


def classify(repository: dict[str, Any]) -> tuple[str, str]:
    """Return a fail-closed rollout state and its operator-facing reason."""
    name = str(repository.get("name") or "")
    ruleset_applies = repository.get("ruleset_applies") is True
    if name in EXEMPT_REPOSITORIES:
        if ruleset_applies:
            return "BLOCK", "documented exception is unexpectedly covered by the central ruleset"
        return "EXEMPT", "documented ruleset exception"

    if not ruleset_applies or repository.get("central_codeql_required") is not True:
        return "BLOCK", "central CodeQL is not enforced by ruleset 18156473"

    expected_head = repository.get("expected_head")
    observed_head = repository.get("central_codeql_head")
    if not isinstance(expected_head, str) or len(expected_head) != 40 or observed_head != expected_head:
        return "BLOCK", "central CodeQL evidence is absent or belongs to another head"

    central_status = repository.get("central_codeql_status")
    default_state = repository.get("default_setup_state")
    active_advanced_upload = repository.get("active_advanced_upload") is True

    if default_state == "configured":
        if active_advanced_upload:
            return "BLOCK", "default setup conflicts with an active advanced CodeQL uploader"
        if central_status in SUCCESS:
            return "READY_DISABLE", "exact-head central CodeQL passed; disable one repository only"
        return "WAIT", "keep default setup until exact-head central CodeQL passes"

    if default_state != "not-configured":
        return "BLOCK", "default-setup state is unavailable or unsupported"
    if central_status in SUCCESS:
        return "VERIFIED", "default setup is off and exact-head central CodeQL passed"
    if central_status in PENDING:
        return "WAIT", "default setup is off; wait for the exact-head central CodeQL verdict"
    if active_advanced_upload:
        return "BLOCK", "central CodeQL failed and default setup cannot coexist with the active uploader"
    return "ROLLBACK", "central CodeQL failed; re-enable default setup before continuing"


def audit(repositories: list[dict[str, Any]]) -> list[tuple[str, str, str]]:
    """Classify every repository snapshot in input order."""
    return [
        (str(repository.get("name") or "<missing>"), *classify(repository))
        for repository in repositories
    ]


def load_payload(path: Path | None, stdin: TextIO) -> list[dict[str, Any]]:
    """Load a repository snapshot array from a file or standard input."""
    if path:
        with path.open(encoding="utf-8") as handle:
            payload = json.load(handle)
    else:
        payload = json.load(stdin)
    if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
        raise ValueError("repository snapshot root must be an array of objects")
    return payload


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshots_json", nargs="?", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        results = audit(load_payload(args.snapshots_json, sys.stdin))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: unable to load CodeQL rollout snapshots: {exc}", file=sys.stderr)
        return 2
    for name, state, reason in results:
        print(f"CODEQL_ROLLOUT repository={name} state={state} reason={reason}")
    return 0 if all(state in {"EXEMPT", "VERIFIED"} for _, state, _ in results) else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
