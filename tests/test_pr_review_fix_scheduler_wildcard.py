"""Regression tests for all-base review-repair scheduler selection."""

from __future__ import annotations

import json

from scripts.ci import pr_review_fix_scheduler as fix


def make_stacked_pr() -> dict[str, object]:
    """Return one same-repository PR whose base is another feature branch."""
    head = "a" * 40
    return {
        "number": 5,
        "isDraft": False,
        "baseRefName": "agent/bootstrap-learning-contracts",
        "baseRefOid": "b" * 40,
        "headRefName": "feat/cefr-language-assessment-contracts",
        "headRefOid": head,
        "headRepository": {
            "nameWithOwner": "ContextualWisdomLab/learning-interoperability-contracts"
        },
        "mergeStateStatus": "CLEAN",
        "reviews": {
            "nodes": [
                {
                    "state": "CHANGES_REQUESTED",
                    "author": {"login": "opencode-agent"},
                    "commit": {"oid": head},
                    "body": "Actionable source-backed finding.",
                }
            ]
        },
        "reviewThreads": {"nodes": []},
    }


def test_base_branch_selector_matches_exact_or_wildcard_only() -> None:
    """The explicit wildcard admits any base without weakening exact callers."""
    assert fix.base_branch_matches("main", "main")
    assert not fix.base_branch_matches("develop", "main")
    assert fix.base_branch_matches("agent/bootstrap-learning-contracts", "*")
    assert not fix.base_branch_matches(None, "main")


def test_process_queue_dispatches_stacked_pr_for_all_base_caller(
    monkeypatch,
    capsys,
) -> None:
    """An all-base caller reaches one actionable stacked PR exactly once."""
    pr = make_stacked_pr()
    calls: list[tuple[object, ...]] = []

    monkeypatch.setattr(fix, "fetch_open_prs", lambda repo, max_prs: [pr])
    monkeypatch.setattr(
        fix,
        "needs_autofix",
        lambda value: (True, ("current-head OpenCode requested changes",)),
    )
    monkeypatch.setattr(fix, "issue_comments", lambda repo, number: [])
    monkeypatch.setattr(
        fix,
        "dispatch_autofix",
        lambda repo, value, workflow, workflow_repository, dry_run, resolve_conflict=False: calls.append(
            (
                "dispatch",
                repo,
                value["number"],
                workflow,
                workflow_repository,
                dry_run,
                resolve_conflict,
            )
        ),
    )
    monkeypatch.setattr(
        fix,
        "create_fix_marker",
        lambda repo, value, dry_run: calls.append(
            ("marker", repo, value["number"], dry_run)
        ),
    )

    exit_code = fix.main(
        [
            "--repo",
            "ContextualWisdomLab/learning-interoperability-contracts",
            "--base-branch",
            "*",
            "--dry-run",
        ]
    )

    assert exit_code == 0
    assert calls == [
        (
            "dispatch",
            "ContextualWisdomLab/learning-interoperability-contracts",
            5,
            "pr-review-autofix.yml",
            "ContextualWisdomLab/.github",
            True,
            False,
        ),
        (
            "marker",
            "ContextualWisdomLab/learning-interoperability-contracts",
            5,
            True,
        ),
    ]
    summary = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert summary["inspected"] == 1
    assert summary["autofix_dispatches"] == 1
