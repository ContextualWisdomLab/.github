"""Regression tests for direct failed-check RCA arbitration."""

from __future__ import annotations

import json
from typing import Any

import pytest

from scripts.ci import pr_review_fix_scheduler as fix


@pytest.fixture(autouse=True)
def isolate_active_autofix_inventory(monkeypatch: Any) -> None:
    """Keep RCA unit tests independent of live GitHub Actions inventory."""
    monkeypatch.setattr(fix, "prepare_autofix_slot", lambda *_args, **_kwargs: False)


def make_pr(*, is_draft: bool = False) -> dict[str, Any]:
    """Return a clean same-repository PR with review and failed-check evidence."""
    head = "a" * 40
    return {
        "number": 7,
        "isDraft": is_draft,
        "baseRefName": "main",
        "baseRefOid": "b" * 40,
        "headRefName": "feature",
        "headRefOid": head,
        "headRepository": {"nameWithOwner": "owner/repo"},
        "mergeStateStatus": "CLEAN",
        "reviews": {
            "nodes": [
                {
                    "state": "CHANGES_REQUESTED",
                    "author": {"login": "opencode-agent"},
                    "commit": {"oid": head},
                    "body": "Actionable source-backed finding with a suggested diff.",
                }
            ]
        },
        "reviewThreads": {"nodes": []},
        "statusCheckRollup": {
            "contexts": {
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "nodes": [
                    {
                        "__typename": "CheckRun",
                        "name": "Application CI",
                        "status": "COMPLETED",
                        "conclusion": "FAILURE",
                    }
                ],
            }
        },
    }


@pytest.mark.parametrize("is_draft", [False, True])
def test_failed_check_rca_precedes_ordinary_review(monkeypatch: Any, is_draft: bool) -> None:
    """A terminal source failure wins over ordinary review feedback, including drafts."""
    captured: dict[str, Any] = {}
    monkeypatch.setattr(fix, "issue_comments", lambda repo, number: [])
    monkeypatch.setattr(
        fix,
        "dispatch_autofix",
        lambda repo, pr, **kwargs: captured.update(kwargs),
    )
    monkeypatch.setattr(fix, "create_fix_marker", lambda repo, pr, dry_run: None)
    args = fix.parse_args(
        ["--repo", "owner/repo", "--base-branch", "main", "--dry-run"]
    )

    action, reasons = fix.inspect_pr("owner/repo", make_pr(is_draft=is_draft), args)

    assert action == "dispatch"
    assert reasons == ("current-head failed check(s) require RCA: Application CI",)
    assert captured["repair_mode"] == "rca"
    assert captured["resolve_conflict"] is False


def test_scan_queue_control_plane_failure_does_not_trigger_rca() -> None:
    """A failed queue scanner cannot consume a source-repair retry by itself."""
    pr = make_pr()
    pr["reviews"] = {"nodes": []}
    pr["statusCheckRollup"]["contexts"]["nodes"] = [
        {
            "__typename": "CheckRun",
            "name": "scan-pr-queue",
            "status": "COMPLETED",
            "conclusion": "FAILURE",
        }
    ]

    assert fix.current_head_failed_checks(pr) == ()
    assert fix.needs_rca_repair(pr) == (False, ())


@pytest.mark.parametrize("draft", [True, False])
def test_conflicted_pr_requires_nondraft_authorization(monkeypatch: Any, draft: bool) -> None:
    """A draft or otherwise unauthorized conflict cannot dispatch repair."""
    pr = make_pr(is_draft=draft)
    pr["mergeStateStatus"] = "DIRTY"
    monkeypatch.setattr(fix, "needs_conflict_resolution", lambda *_args, **_kwargs: (False, ()))
    args = fix.parse_args(["--repo", "owner/repo", "--base-branch", "main", "--dry-run"])
    action, reasons = fix.inspect_pr("owner/repo", pr, args)
    assert action == "skip"
    assert reasons == (("draft PR",) if draft else ("merge conflict is not authorized for repair",))


@pytest.mark.parametrize(
    "workflow_name",
    ["OpenCode Review", "Required OpenCode Review", "OpenCode PR Review"],
)
def test_opencode_control_plane_workflow_failure_does_not_trigger_rca(
    workflow_name: str,
) -> None:
    """Renamed jobs in categorically excluded review workflows stay excluded."""
    pr = make_pr()
    pr["reviews"] = {"nodes": []}
    pr["statusCheckRollup"]["contexts"]["nodes"] = [
        {
            "__typename": "CheckRun",
            "name": "renamed review job",
            "status": "COMPLETED",
            "conclusion": "FAILURE",
            "checkSuite": {"workflowRun": {"workflow": {"name": workflow_name}}},
        }
    ]

    assert fix.current_head_failed_checks(pr) == ()
    assert fix.needs_rca_repair(pr) == (False, ())


@pytest.mark.parametrize("single_pr", [False, True])
def test_process_queue_completes_check_pages_before_rca_decision(
    monkeypatch: Any, capsys: Any, single_pr: bool
) -> None:
    """Queue and single fetches load later failures before choosing repair mode."""
    pr = make_pr()
    pr["statusCheckRollup"]["contexts"] = {
        "pageInfo": {"hasNextPage": True, "endCursor": "page_1"},
        "nodes": [
            {
                "__typename": "CheckRun",
                "name": "Application CI",
                "status": "COMPLETED",
                "conclusion": "SUCCESS",
            }
        ],
    }
    order: list[str] = []
    captured: dict[str, Any] = {}

    def complete_pages(repo: str, candidate: dict[str, Any]) -> None:
        order.append("paginate")
        contexts = candidate["statusCheckRollup"]["contexts"]
        contexts["nodes"].append(
            {
                "__typename": "CheckRun",
                "name": "Security Scan",
                "status": "COMPLETED",
                "conclusion": "FAILURE",
            }
        )
        contexts["pageInfo"] = {"hasNextPage": False, "endCursor": None}

    def dispatch(repo: str, candidate: dict[str, Any], **kwargs: Any) -> None:
        order.append("dispatch")
        captured.update(kwargs)

    monkeypatch.setattr(fix, "fetch_open_prs", lambda repo, max_prs: [pr])
    monkeypatch.setattr(fix, "fetch_pr", lambda repo, number: [pr])
    monkeypatch.setattr(fix, "complete_paginated_pr_contexts", complete_pages)
    monkeypatch.setattr(fix, "issue_comments", lambda repo, number: [])
    monkeypatch.setattr(fix, "dispatch_autofix", dispatch)
    monkeypatch.setattr(fix, "create_fix_marker", lambda repo, candidate, dry_run: None)
    argv = ["--repo", "owner/repo", "--base-branch", "main", "--dry-run"]
    if single_pr:
        argv.extend(["--pr-number", "7"])
    args = fix.parse_args(argv)

    assert fix.process_queue(args) == 0

    assert order == ["paginate", "dispatch"]
    assert captured["repair_mode"] == "rca"
    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert payload["autofix_dispatches"] == 1
    assert payload["decisions"][0]["reasons"] == [
        "current-head failed check(s) require RCA: Security Scan"
    ]


def test_process_queue_isolates_one_pagination_failure(
    monkeypatch: Any, capsys: Any
) -> None:
    """One incomplete rollup waits while another PR still dispatches repair."""
    blocked = make_pr()
    blocked["number"] = 1
    repairable = make_pr()
    repairable["number"] = 2
    paginated: list[int] = []
    dispatched: list[int] = []

    def complete_pages(repo: str, candidate: dict[str, Any]) -> None:
        paginated.append(int(candidate["number"]))
        if candidate["number"] == 1:
            raise RuntimeError("status rollup pagination unavailable")

    monkeypatch.setattr(
        fix,
        "fetch_open_prs",
        lambda repo, max_prs: [blocked, repairable],
    )
    monkeypatch.setattr(fix, "complete_paginated_pr_contexts", complete_pages)
    monkeypatch.setattr(fix, "issue_comments", lambda repo, number: [])
    monkeypatch.setattr(
        fix,
        "dispatch_autofix",
        lambda repo, candidate, **kwargs: dispatched.append(int(candidate["number"])),
    )
    monkeypatch.setattr(fix, "create_fix_marker", lambda repo, candidate, dry_run: None)
    args = fix.parse_args(
        [
            "--repo",
            "owner/repo",
            "--base-branch",
            "main",
            "--max-dispatches",
            "2",
            "--dry-run",
        ]
    )

    assert fix.process_queue(args) == 0

    assert paginated == [1, 2]
    assert dispatched == [2]
    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    decisions = {entry["pr"]: entry for entry in payload["decisions"]}
    assert decisions[1]["action"] == "wait"
    assert "status-context pagination failed" in decisions[1]["reasons"][0]
    assert decisions[2]["action"] == "dispatch"


def test_process_queue_does_not_paginate_out_of_scope_pr(
    monkeypatch: Any, capsys: Any
) -> None:
    """Base-filtered PRs do not spend status-rollup pagination requests."""
    out_of_scope = make_pr()
    out_of_scope["number"] = 1
    out_of_scope["baseRefName"] = "develop"
    in_scope = make_pr()
    in_scope["number"] = 2
    paginated: list[int] = []

    def complete_pages(repo: str, candidate: dict[str, Any]) -> None:
        paginated.append(int(candidate["number"]))
        if candidate["number"] == 1:
            raise AssertionError("out-of-scope PR must not be paginated")

    monkeypatch.setattr(
        fix,
        "fetch_open_prs",
        lambda repo, max_prs: [out_of_scope, in_scope],
    )
    monkeypatch.setattr(fix, "complete_paginated_pr_contexts", complete_pages)
    monkeypatch.setattr(fix, "issue_comments", lambda repo, number: [])
    monkeypatch.setattr(fix, "dispatch_autofix", lambda *args, **kwargs: None)
    monkeypatch.setattr(fix, "create_fix_marker", lambda *args, **kwargs: None)
    args = fix.parse_args(
        ["--repo", "owner/repo", "--base-branch", "main", "--dry-run"]
    )

    assert fix.process_queue(args) == 0

    assert paginated == [2]
    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    decisions = {entry["pr"]: entry for entry in payload["decisions"]}
    assert decisions[1]["action"] == "skip"
    assert decisions[2]["action"] == "dispatch"
