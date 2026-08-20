"""Tests for exact ordered-stack review repair selection."""

from __future__ import annotations

import argparse
import json

import pytest

from scripts.ci import pr_review_fix_stack_scheduler as stack


def make_pr(
    number: int,
    *,
    base_name: str,
    base_oid: str,
    head_name: str,
    head_oid: str,
) -> dict:
    """Return one minimal scheduler-shaped pull request."""

    return {
        "number": number,
        "baseRefName": base_name,
        "baseRefOid": base_oid,
        "headRefName": head_name,
        "headRefOid": head_oid,
    }


def arguments(numbers: tuple[int, ...]) -> argparse.Namespace:
    """Return runtime arguments consumed by the stack driver."""

    return argparse.Namespace(
        repo="ContextualWisdomLab/LineageWeave",
        base_branch="main",
        pull_request_numbers=numbers,
        max_prs=6,
        max_dispatches=1,
        retry_hours=2,
        resolve_unreviewed_conflicts=True,
        autofix_workflow="pr-review-autofix.yml",
        autofix_repository="ContextualWisdomLab/.github",
        dry_run=False,
    )


def test_parse_pull_request_numbers_preserves_order_and_rejects_ambiguity() -> None:
    """The explicit queue is positive, unique, bounded, and ordered."""

    assert stack.parse_pull_request_numbers("258, 260,261", maximum=3) == (
        258,
        260,
        261,
    )
    for raw, maximum in (
        ("", 3),
        ("0", 3),
        ("x", 3),
        ("258,258", 3),
        ("1,2", 1),
    ):
        with pytest.raises(ValueError):
            stack.parse_pull_request_numbers(raw, maximum=maximum)
    with pytest.raises(ValueError):
        stack.parse_pull_request_numbers("1", maximum=0)


def test_stack_dispatches_once_in_declared_dependency_order(
    monkeypatch,
    capsys,
) -> None:
    """A clean parent advances to the first actionable child and then stops."""

    root = make_pr(
        258,
        base_name="main",
        base_oid="0" * 40,
        head_name="feat/root",
        head_oid="1" * 40,
    )
    child = make_pr(
        260,
        base_name="feat/root",
        base_oid="1" * 40,
        head_name="feat/child",
        head_oid="2" * 40,
    )
    grandchild = make_pr(
        261,
        base_name="feat/child",
        base_oid="2" * 40,
        head_name="feat/grandchild",
        head_oid="3" * 40,
    )
    records = {258: root, 260: child, 261: grandchild}
    fetched: list[int] = []
    inspected: list[tuple[int, str]] = []

    def fake_fetch(repo: str, number: int) -> list[dict]:
        assert repo == "ContextualWisdomLab/LineageWeave"
        fetched.append(number)
        return [records[number]]

    def fake_inspect(repo: str, pr: dict, args: argparse.Namespace):
        assert repo == "ContextualWisdomLab/LineageWeave"
        inspected.append((pr["number"], args.base_branch))
        if pr["number"] == 258:
            return "skip", (stack.NO_REPAIR_REASON,)
        return "dispatch", ("current-head OpenCode requested changes",)

    monkeypatch.setattr(stack, "fetch_pr", fake_fetch)
    monkeypatch.setattr(stack, "inspect_pr", fake_inspect)

    assert stack.process_stack(arguments((258, 260, 261))) == 0
    assert fetched == [258, 260]
    assert inspected == [(258, "main"), (260, "feat/root")]
    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert payload["autofix_dispatches"] == 1
    assert [decision["pr"] for decision in payload["decisions"]] == [258, 260]


def test_stack_waits_when_child_base_sha_is_stale(monkeypatch, capsys) -> None:
    """A stale descendant waits for restacking instead of failing or mutating."""

    root = make_pr(
        258,
        base_name="main",
        base_oid="0" * 40,
        head_name="feat/root",
        head_oid="1" * 40,
    )
    stale_child = make_pr(
        260,
        base_name="feat/root",
        base_oid="9" * 40,
        head_name="feat/child",
        head_oid="2" * 40,
    )
    records = {258: root, 260: stale_child}
    inspected: list[int] = []
    monkeypatch.setattr(stack, "fetch_pr", lambda repo, number: [records[number]])

    def fake_inspect(repo: str, pr: dict, args: argparse.Namespace):
        inspected.append(pr["number"])
        return "skip", (stack.NO_REPAIR_REASON,)

    monkeypatch.setattr(stack, "inspect_pr", fake_inspect)

    assert stack.process_stack(arguments((258, 260))) == 0
    assert inspected == [258]
    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert payload["decisions"][-1]["action"] == "wait"
    assert "expected parent head" in payload["decisions"][-1]["reasons"][0]


def test_stack_fails_closed_on_wrong_parent_branch(monkeypatch, capsys) -> None:
    """A child targeting an unexpected branch is a structural contract failure."""

    root = make_pr(
        258,
        base_name="main",
        base_oid="0" * 40,
        head_name="feat/root",
        head_oid="1" * 40,
    )
    wrong_child = make_pr(
        260,
        base_name="feat/other",
        base_oid="1" * 40,
        head_name="feat/child",
        head_oid="2" * 40,
    )
    records = {258: root, 260: wrong_child}
    monkeypatch.setattr(stack, "fetch_pr", lambda repo, number: [records[number]])
    monkeypatch.setattr(
        stack,
        "inspect_pr",
        lambda repo, pr, args: ("skip", (stack.NO_REPAIR_REASON,)),
    )

    assert stack.process_stack(arguments((258, 260))) == 1
    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert payload["decisions"][-1]["action"] == "error"
    assert "expected 'feat/root'" in payload["decisions"][-1]["reasons"][0]


def test_stack_stops_on_wait_draft_and_nonrepair_skip(monkeypatch) -> None:
    """An in-flight or structurally blocked parent prevents descendant repair."""

    pr = make_pr(
        258,
        base_name="main",
        base_oid="0" * 40,
        head_name="feat/root",
        head_oid="1" * 40,
    )
    fetched: list[int] = []

    def fake_fetch(repo: str, number: int) -> list[dict]:
        fetched.append(number)
        return [pr]

    monkeypatch.setattr(stack, "fetch_pr", fake_fetch)
    monkeypatch.setattr(
        stack,
        "inspect_pr",
        lambda repo, item, args: ("wait", ("recent autofix marker exists",)),
    )
    assert stack.process_stack(arguments((258, 260))) == 0
    assert fetched == [258]

    fetched.clear()
    monkeypatch.setattr(
        stack,
        "inspect_pr",
        lambda repo, item, args: ("skip", ("draft PR",)),
    )
    assert stack.process_stack(arguments((258, 260))) == 0
    assert fetched == [258]


def test_stack_handles_missing_pr_and_cli_contract(monkeypatch) -> None:
    """Missing records and unsafe CLI values fail before descendant mutation."""

    monkeypatch.setattr(stack, "fetch_pr", lambda repo, number: [])
    assert stack.process_stack(arguments((258,))) == 1
    assert stack.main(["--self-test"]) == 0
    parsed = stack.parse_args(
        [
            "--repo",
            "ContextualWisdomLab/LineageWeave",
            "--base-branch",
            "main",
            "--pull-request-numbers",
            "258,260",
            "--max-prs",
            "2",
            "--max-dispatches",
            "1",
        ]
    )
    assert parsed.pull_request_numbers == (258, 260)
    for bad in (
        [
            "--repo",
            "bad repo",
            "--base-branch",
            "main",
            "--pull-request-numbers",
            "258",
        ],
        [
            "--repo",
            "owner/repo",
            "--base-branch",
            "-bad",
            "--pull-request-numbers",
            "258",
        ],
        [
            "--repo",
            "owner/repo",
            "--base-branch",
            "main",
            "--pull-request-numbers",
            "258",
            "--max-prs",
            "0",
        ],
        [
            "--repo",
            "owner/repo",
            "--base-branch",
            "main",
            "--pull-request-numbers",
            "258",
            "--max-dispatches",
            "2",
        ],
        [
            "--repo",
            "owner/repo",
            "--base-branch",
            "main",
            "--pull-request-numbers",
            "258",
            "--retry-hours",
            "0",
        ],
    ):
        with pytest.raises(SystemExit):
            stack.parse_args(bad)


def test_stack_handles_inspection_failure_and_empty_queue(
    monkeypatch,
    capsys,
) -> None:
    """Inspection errors fail closed and an already-empty queue reports cleanly."""

    pr = make_pr(
        258,
        base_name="main",
        base_oid="0" * 40,
        head_name="feat/root",
        head_oid="1" * 40,
    )
    monkeypatch.setattr(stack, "fetch_pr", lambda repo, number: [pr])
    monkeypatch.setattr(
        stack,
        "inspect_pr",
        lambda repo, item, args: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    assert stack.process_stack(arguments((258,))) == 1
    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert payload["decisions"][0]["reasons"] == ["boom"]

    empty_args = arguments(())
    assert stack.process_stack(empty_args) == 0
    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert payload["inspected"] == 0


def test_cli_covers_invalid_base_stack_value_and_normal_main(monkeypatch) -> None:
    """CLI validation reports unsafe values and main delegates normal execution."""

    with pytest.raises(SystemExit):
        stack.parse_args(
            [
                "--repo",
                "owner/repo",
                "--base-branch",
                "",
                "--pull-request-numbers",
                "258",
            ]
        )
    with pytest.raises(SystemExit):
        stack.parse_args(
            [
                "--repo",
                "owner/repo",
                "--base-branch",
                "main",
                "--pull-request-numbers",
                "bad",
            ]
        )

    seen: list[tuple[int, ...]] = []
    monkeypatch.setattr(
        stack,
        "process_stack",
        lambda args: seen.append(args.pull_request_numbers) or 7,
    )
    assert (
        stack.main(
            [
                "--repo",
                "owner/repo",
                "--base-branch",
                "main",
                "--pull-request-numbers",
                "258",
            ]
        )
        == 7
    )
    assert seen == [(258,)]
