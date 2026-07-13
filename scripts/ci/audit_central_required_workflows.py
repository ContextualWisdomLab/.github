#!/usr/bin/env python3
"""Audit the live ContextualWisdomLab central required-workflow ruleset."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, TextIO


RULESET_ID = 18156473
RULESET_NAME = "CWL Central required workflows"
SOURCE_REPOSITORY_ID = 1274066402
SOURCE_REF = "refs/heads/main"
REQUIRED_WORKFLOW_PATHS = (
    ".github/workflows/close-empty-pr.yml",
    ".github/workflows/opencode-review.yml",
    ".github/workflows/pr-review-merge-scheduler.yml",
    ".github/workflows/security-scan.yml",
    ".github/workflows/strix.yml",
    ".github/workflows/sast-semgrep.yml",
)


def _typed_rules(payload: dict[str, Any], rule_type: str) -> list[dict[str, Any]]:
    """Return well-formed rules matching ``rule_type``."""
    rules = payload.get("rules")
    if not isinstance(rules, list):
        return []
    return [
        rule
        for rule in rules
        if isinstance(rule, dict) and rule.get("type") == rule_type
    ]


def audit_ruleset(payload: dict[str, Any]) -> list[str]:
    """Return explicit drift reasons for a live organization ruleset payload."""
    errors: list[str] = []

    if payload.get("id") != RULESET_ID:
        errors.append(f"expected ruleset id {RULESET_ID}")
    if payload.get("name") != RULESET_NAME:
        errors.append(f"expected ruleset name {RULESET_NAME}")
    if payload.get("target") != "branch":
        errors.append("central ruleset target is not branch")
    if payload.get("enforcement") != "active":
        errors.append("central ruleset enforcement is not active")

    conditions = payload.get("conditions")
    conditions = conditions if isinstance(conditions, dict) else {}
    repository_names = conditions.get("repository_name")
    repository_names = repository_names if isinstance(repository_names, dict) else {}
    if "~ALL" not in (repository_names.get("include") or []):
        errors.append("central ruleset does not include all repositories")
    excluded_repositories = set(repository_names.get("exclude") or [])
    expected_exclusions = {".github", "argos", "noema"}
    if excluded_repositories != expected_exclusions:
        errors.append(
            "central ruleset repository exclusions drifted: "
            f"expected {sorted(expected_exclusions)}, got {sorted(excluded_repositories)}"
        )

    ref_names = conditions.get("ref_name")
    ref_names = ref_names if isinstance(ref_names, dict) else {}
    if "~DEFAULT_BRANCH" not in (ref_names.get("include") or []):
        errors.append("central ruleset does not target every default branch")

    workflow_rules = _typed_rules(payload, "workflows")
    if len(workflow_rules) != 1:
        errors.append(f"expected one workflows rule, found {len(workflow_rules)}")
        workflows: list[Any] = []
    else:
        parameters = workflow_rules[0].get("parameters")
        parameters = parameters if isinstance(parameters, dict) else {}
        workflows = parameters.get("workflows")
        workflows = workflows if isinstance(workflows, list) else []

    workflows_by_path: dict[str, list[dict[str, Any]]] = {}
    for workflow in workflows:
        if not isinstance(workflow, dict) or not isinstance(workflow.get("path"), str):
            continue
        workflows_by_path.setdefault(workflow["path"], []).append(workflow)

    for path in REQUIRED_WORKFLOW_PATHS:
        matches = workflows_by_path.get(path, [])
        if not matches:
            errors.append(f"missing central required workflow {path}")
            continue
        if len(matches) != 1:
            errors.append(f"central required workflow {path} is configured {len(matches)} times")
        if not any(
            workflow.get("repository_id") == SOURCE_REPOSITORY_ID
            and workflow.get("ref") == SOURCE_REF
            for workflow in matches
        ):
            errors.append(
                f"central required workflow {path} must use source repository "
                f"{SOURCE_REPOSITORY_ID} at {SOURCE_REF}"
            )

    review_rules = _typed_rules(payload, "pull_request")
    if len(review_rules) != 1:
        errors.append(f"expected one pull_request rule, found {len(review_rules)}")
    else:
        parameters = review_rules[0].get("parameters")
        parameters = parameters if isinstance(parameters, dict) else {}
        approving_reviews = parameters.get("required_approving_review_count")
        if not isinstance(approving_reviews, int) or approving_reviews < 1:
            errors.append("at least one approving review is not required")
        if parameters.get("dismiss_stale_reviews_on_push") is not True:
            errors.append("stale-review dismissal on push is disabled")
        if parameters.get("require_last_push_approval") is not True:
            errors.append("last-push approval protection is disabled")
        if parameters.get("required_review_thread_resolution") is not True:
            errors.append("review-thread resolution protection is disabled")
        allowed_methods = set(parameters.get("allowed_merge_methods") or [])
        if not {"merge", "squash"}.issubset(allowed_methods):
            errors.append("merge and squash are not both allowed merge methods")

    if not _typed_rules(payload, "deletion"):
        errors.append("default-branch deletion protection is missing")
    if not _typed_rules(payload, "non_fast_forward"):
        errors.append("default-branch non-fast-forward protection is missing")

    return errors


def load_payload(path: Path | None, stdin: TextIO) -> dict[str, Any]:
    """Load a ruleset object from ``path`` or standard input."""
    if path is None:
        payload = json.load(stdin)
    else:
        with path.open(encoding="utf-8") as handle:
            payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("ruleset JSON root must be an object")
    return payload


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse the optional ruleset JSON path."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ruleset_json", nargs="?", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Audit a ruleset payload and print every actionable drift reason."""
    args = parse_args(argv)
    try:
        payload = load_payload(args.ruleset_json, sys.stdin)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: unable to load ruleset JSON: {exc}", file=sys.stderr)
        return 2

    errors = audit_ruleset(payload)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        print(
            f"FAIL: ruleset {RULESET_ID} has {len(errors)} governance drift reason(s)",
            file=sys.stderr,
        )
        return 1

    print(
        f"PASS: ruleset {RULESET_ID} enforces "
        f"{len(REQUIRED_WORKFLOW_PATHS)} central required workflows"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through main()
    raise SystemExit(main())
