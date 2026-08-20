#!/usr/bin/env python3
"""Dispatch at most one repair across an explicitly ordered pull-request stack."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import Any

try:
    from pr_review_fix_scheduler import (
        DEFAULT_AUTOFIX_REPOSITORY,
        DEFAULT_AUTOFIX_WORKFLOW,
        REPO_RE,
        fetch_pr,
        inspect_pr,
    )
except ModuleNotFoundError:
    from scripts.ci.pr_review_fix_scheduler import (
        DEFAULT_AUTOFIX_REPOSITORY,
        DEFAULT_AUTOFIX_WORKFLOW,
        REPO_RE,
        fetch_pr,
        inspect_pr,
    )

BRANCH_RE = re.compile(r"^(?!-)[A-Za-z0-9._/-]+$")
NUMBER_RE = re.compile(r"^[1-9][0-9]*$")
SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
MAX_BRANCH_NAME_LENGTH = 255
VALID_ACTIONS = frozenset({"dispatch", "error", "skip", "wait"})
NO_REPAIR_REASON = (
    "no current-head autofixable review, failed-check RCA, or approved merge conflict"
)


def parse_pull_request_numbers(raw: str, *, maximum: int) -> tuple[int, ...]:
    """Return unique positive PR numbers while preserving caller order."""

    if maximum < 1:
        raise ValueError("maximum must be positive")
    tokens = tuple(part.strip() for part in raw.split(","))
    if not tokens or any(not token for token in tokens):
        raise ValueError("at least one pull request number is required")
    numbers: list[int] = []
    seen: set[int] = set()
    for token in tokens:
        if not NUMBER_RE.fullmatch(token):
            raise ValueError(f"invalid pull request number: {token!r}")
        number = int(token)
        if number in seen:
            raise ValueError(f"duplicate pull request number: {number}")
        seen.add(number)
        numbers.append(number)
    if len(numbers) > maximum:
        raise ValueError(
            f"pull request stack has {len(numbers)} entries; maximum is {maximum}"
        )
    return tuple(numbers)


def _single_pull_request(repo: str, number: int) -> dict[str, Any]:
    """Fetch exactly one pull request snapshot or fail closed."""

    records = fetch_pr(repo, number)
    if not isinstance(records, list):
        raise RuntimeError("pull request response must be a list")
    if len(records) != 1:
        raise RuntimeError(
            f"expected one pull request for #{number}; received {len(records)}"
        )
    record = records[0]
    if not isinstance(record, dict):
        raise RuntimeError("pull request response item must be an object")
    if type(record.get("number")) is not int or record["number"] != number:
        raise RuntimeError(f"pull request response number does not match #{number}")
    for field in ("baseRefName", "headRefName"):
        branch_name = record.get(field)
        if (
            not isinstance(branch_name, str)
            or len(branch_name) > MAX_BRANCH_NAME_LENGTH
            or ".." in branch_name
            or not BRANCH_RE.fullmatch(branch_name)
        ):
            raise RuntimeError(f"pull request response has an unsafe {field}")
    for field in ("baseRefOid", "headRefOid"):
        if not isinstance(record.get(field), str) or not SHA_RE.fullmatch(record[field]):
            raise RuntimeError(f"pull request response has an invalid {field}")
    return record


def _normalize_decision(
    decision: object,
) -> tuple[str, tuple[str, ...]]:
    """Validate a shared scheduler decision before recording or acting on it."""

    if not isinstance(decision, tuple) or len(decision) != 2:
        return "error", ("shared scheduler returned a malformed decision",)
    action, reasons = decision
    if not isinstance(action, str) or action not in VALID_ACTIONS:
        return "error", ("shared scheduler returned an unknown action",)
    if not isinstance(reasons, (tuple, list)) or not reasons:
        return "error", ("shared scheduler returned empty reasons",)
    if any(not isinstance(reason, str) or not reason.strip() for reason in reasons):
        return "error", ("shared scheduler returned non-string reasons",)
    return str(action), tuple(reason.strip() for reason in reasons)


def _base_branch_error(
    pr: dict[str, Any],
    *,
    expected_base_name: str,
) -> str | None:
    """Return a structural error when a child targets the wrong parent branch."""

    actual_name = str(pr.get("baseRefName") or "")
    if actual_name == expected_base_name:
        return None
    return (
        f"PR #{pr.get('number')} base branch is {actual_name!r}; "
        f"expected {expected_base_name!r}"
    )


def _stale_base_reason(
    pr: dict[str, Any],
    *,
    expected_base_oid: str | None,
) -> str | None:
    """Return a wait reason when a child is not based on the current parent head."""

    if expected_base_oid is None:
        return None
    actual_oid = str(pr.get("baseRefOid") or "")
    if actual_oid.lower() == expected_base_oid.lower():
        return None
    return (
        f"PR #{pr.get('number')} base SHA is {actual_oid or '<missing>'}; "
        f"expected parent head {expected_base_oid}; restack before descendant repair"
    )


def _summary(
    *,
    inspected: int,
    dispatched: int,
    pull_request_numbers: tuple[int, ...],
    decisions: list[dict[str, Any]],
) -> str:
    """Serialize one deterministic machine-readable stack decision summary."""

    return json.dumps(
        {
            "inspected": inspected,
            "autofix_dispatches": dispatched,
            "stack_prs": list(pull_request_numbers),
            "decisions": decisions,
        },
        sort_keys=True,
    )


def process_stack(args: argparse.Namespace) -> int:
    """Inspect the stack in order and stop after one dispatch or blocker."""

    previous: dict[str, Any] | None = None
    previous_number: int | None = None
    inspected = 0
    dispatched = 0
    failed = False
    decisions: list[dict[str, Any]] = []
    for number in args.pull_request_numbers:
        pr: dict[str, Any] | None = None
        action = ""
        reasons: tuple[str, ...] = ()
        if previous is not None and previous_number is not None:
            try:
                refreshed_parent = _single_pull_request(args.repo, previous_number)
            except (RuntimeError, OSError, ValueError) as exc:
                action, reasons = "error", (str(exc),)
            else:
                if refreshed_parent["headRefOid"].lower() != previous["headRefOid"].lower():
                    action, reasons = "wait", (
                        f"parent PR #{previous_number} head moved from "
                        f"{previous['headRefOid']} to {refreshed_parent['headRefOid']}; "
                        "restack before descendant repair",
                    )
                else:
                    previous = refreshed_parent
        if not action:
            try:
                pr = _single_pull_request(args.repo, number)
            except (RuntimeError, OSError, ValueError) as exc:
                action, reasons = "error", (str(exc),)
        if not action:
            expected_name = (
                args.base_branch
                if previous is None
                else str(previous.get("headRefName") or "")
            )
            expected_oid = (
                None
                if previous is None
                else str(previous.get("headRefOid") or "")
            )
            branch_error = _base_branch_error(
                pr,
                expected_base_name=expected_name,
            )
            stale_reason = _stale_base_reason(
                pr,
                expected_base_oid=expected_oid,
            )
            if branch_error is not None:
                action, reasons = "error", (branch_error,)
            elif stale_reason is not None:
                action, reasons = "wait", (stale_reason,)
            else:
                local_args = argparse.Namespace(**vars(args))
                local_args.base_branch = expected_name
                try:
                    action, reasons = _normalize_decision(
                        inspect_pr(args.repo, pr, local_args)
                    )
                except (RuntimeError, OSError, ValueError) as exc:
                    action, reasons = "error", (str(exc),)

        inspected += 1
        decisions.append(
            {"pr": number, "action": action, "reasons": list(reasons)}
        )
        print(f"PR #{number}: {action}: {'; '.join(reasons)}")
        if action == "dispatch":
            dispatched = 1
            break
        if action == "error":
            failed = True
            break
        if action == "wait":
            break
        if action != "skip" or tuple(reasons) != (NO_REPAIR_REASON,):
            break
        previous = pr
        previous_number = number

    print(
        _summary(
            inspected=inspected,
            dispatched=dispatched,
            pull_request_numbers=args.pull_request_numbers,
            decisions=decisions,
        )
    )
    return 1 if failed else 0


def self_test() -> int:
    """Exercise parser invariants without network or repository mutation."""

    assert parse_pull_request_numbers("1,2,3", maximum=3) == (1, 2, 3)
    try:
        parse_pull_request_numbers("1,1", maximum=3)
    except ValueError:
        pass
    else:  # pragma: no cover - defensive contract
        raise AssertionError("duplicate PR numbers must fail")
    print("stack self-test passed")
    return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse the ordered-stack scheduler CLI contract."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--base-branch", default=os.environ.get("DEFAULT_BRANCH", ""))
    parser.add_argument(
        "--pull-request-numbers",
        default=os.environ.get("PULL_REQUEST_NUMBERS", ""),
    )
    parser.add_argument("--max-prs", type=int, default=50)
    parser.add_argument("--max-dispatches", type=int, default=1)
    parser.add_argument("--retry-hours", type=int, default=24)
    parser.add_argument("--resolve-unreviewed-conflicts", action="store_true")
    parser.add_argument("--autofix-workflow", default=DEFAULT_AUTOFIX_WORKFLOW)
    parser.add_argument("--autofix-repository", default=DEFAULT_AUTOFIX_REPOSITORY)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    if args.self_test:
        return args
    if not REPO_RE.fullmatch(args.repo):
        parser.error("--repo must be in OWNER/NAME form")
    if not BRANCH_RE.fullmatch(args.base_branch):
        parser.error("--base-branch is required and must be a safe branch name")
    if args.max_prs < 1:
        parser.error("--max-prs must be positive")
    if args.max_dispatches != 1:
        parser.error("ordered stack scheduling requires --max-dispatches 1")
    if args.retry_hours < 1:
        parser.error("--retry-hours must be positive")
    try:
        args.pull_request_numbers = parse_pull_request_numbers(
            args.pull_request_numbers,
            maximum=args.max_prs,
        )
    except ValueError as exc:
        parser.error(str(exc))
    return args


def main(argv: list[str] | None = None) -> int:
    """Run the self-test or process one ordered stack."""

    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.self_test:
        return self_test()
    return process_stack(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
