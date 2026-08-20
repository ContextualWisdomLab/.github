"""Close Noema handoff, approval, rebase, and scheduler branch coverage."""

from __future__ import annotations

import argparse
import json
from typing import Any

import pytest

from scripts.ci import noema_review_gate as noema
from scripts.ci import noema_review_handoff as handoff
from scripts.ci import opencode_existing_approval_gate as approval_gate
from scripts.ci import pr_auto_rebase as auto_rebase
from scripts.ci import pr_review_autofix_context as autofix_context
from scripts.ci import pr_review_fix_scheduler as fix_scheduler
from scripts.ci import pr_review_merge_scheduler as merge_scheduler


def test_noema_public_dns_result_reaches_valid_model_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Globally routable DNS answers pass the SSRF gate and return strict JSON."""

    monkeypatch.setenv("NOEMA_LLM_API_URL", "https://review.example.invalid/v1/chat")
    monkeypatch.setenv("NOEMA_LLM_API_KEY", "test-key")
    monkeypatch.setattr(
        noema.socket,
        "getaddrinfo",
        lambda *_args: [(2, 1, 6, "", ("8.8.8.8", 0))],
    )

    class Response:
        """Context-managed deterministic LLM response."""

        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *_args: object) -> bool:
            return False

        def read(self) -> bytes:
            return json.dumps(
                {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "decision": "approve",
                                        "summary": "clean",
                                        "findings": [],
                                    }
                                )
                            }
                        }
                    ]
                }
            ).encode()

    class Opener:
        """Open one deterministic provider response."""

        def open(self, _request: Any, timeout: int) -> Response:
            assert timeout == 120
            return Response()

    monkeypatch.setattr(noema.urllib.request, "build_opener", lambda *_args: Opener())
    verdict = noema.call_llm("owner/repo", 1, {"headRefOid": "a" * 40}, "diff", False)
    assert verdict["decision"] == "approve"


def test_noema_handoff_returns_current_terminal_state() -> None:
    """A marker-bearing exact-head Noema approval is recognized immediately."""

    head = "a" * 40
    reviews = [
        {
            "commit_id": head,
            "user": {"login": handoff.NOEMA_REVIEW_AUTHOR},
            "body": handoff.NOEMA_REVIEW_MARKER,
            "state": "approved",
        }
    ]
    assert handoff.noema_review_state(reviews, head) == "APPROVED"


def test_adversarial_evidence_ignores_nonobject_json_block() -> None:
    """A parseable scalar block does not replace the last structured evidence object."""

    body = (
        '## Adversarial validation\n```json\n{"status":"passed"}\n```\n'
        '## Adversarial validation\n```json\n[1,2,3]\n```'
    )
    assert approval_gate.extract_adversarial_evidence(body) == {"status": "passed"}


def test_auto_rebase_pagination_exits_after_exact_requested_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pagination terminates through the loop condition after filling the requested cap."""

    payload = {
        "data": {
            "repository": {
                "pullRequests": {
                    "nodes": [{"number": 1}],
                    "pageInfo": {"hasNextPage": True, "endCursor": "next"},
                }
            }
        }
    }
    monkeypatch.setattr(auto_rebase, "gh_graphql", lambda *_args, **_kwargs: payload)
    assert auto_rebase.fetch_open_prs("owner/repo", 1) == [{"number": 1}]


def test_autofix_context_renders_legacy_status_context() -> None:
    """Legacy status contexts remain visible in bounded autofix evidence."""

    assert autofix_context.check_summary(
        [{"__typename": "StatusContext", "context": "security", "state": "SUCCESS"}]
    ) == ["- security: SUCCESS"]


def test_fix_scheduler_queue_includes_eligible_pr_without_fix_need(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An eligible but clean PR traverses the no-comment pre-scan branch."""

    pr = {
        "number": 1,
        "isDraft": False,
        "baseRefName": "main",
        "headRepository": {"nameWithOwner": "owner/repo"},
    }
    monkeypatch.setattr(fix_scheduler, "fetch_open_prs", lambda *_args: [pr])
    monkeypatch.setattr(fix_scheduler, "same_repository_head", lambda *_args: True)
    monkeypatch.setattr(fix_scheduler, "needs_autofix", lambda _pr: (False, ()))
    monkeypatch.setattr(
        fix_scheduler,
        "needs_conflict_resolution",
        lambda _pr, **_kwargs: (False, ()),
    )
    monkeypatch.setattr(
        fix_scheduler, "inspect_pr", lambda *_args, **_kwargs: ("skip", ("clean",))
    )
    args = argparse.Namespace(
        repo="owner/repo",
        pr_number=None,
        max_prs=10,
        base_branch="main",
        max_dispatches=1,
        dry_run=True,
    )
    assert fix_scheduler.process_queue(args) == 0
    assert '"inspected": 1' in capsys.readouterr().out


def test_merge_scheduler_rest_pagination_exits_at_requested_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """REST pagination exits through the loop condition after the exact cap."""

    payload = [{"number": 1}, {"number": 2}]
    monkeypatch.setattr(merge_scheduler, "gh_api_json", lambda _path: payload)
    monkeypatch.setattr(
        merge_scheduler,
        "rest_pr_node",
        lambda _repo, pr: {"number": pr["number"]},
    )
    assert merge_scheduler.fetch_open_prs_rest("owner/repo", 2) == [
        {"number": 1},
        {"number": 2},
    ]


def test_merge_scheduler_keeps_newest_check_when_older_duplicate_arrives() -> None:
    """An older duplicate check run cannot replace the newest successful state."""

    def check(started: str, conclusion: str) -> dict[str, Any]:
        return {
            "__typename": "CheckRun",
            "name": "quality",
            "startedAt": started,
            "status": "COMPLETED",
            "conclusion": conclusion,
            "checkSuite": {"workflowRun": {"workflow": {"name": "CI"}}},
        }

    pr = {
        "statusCheckRollup": {
            "contexts": {
                "nodes": [
                    check("2026-08-05T02:00:00Z", "SUCCESS"),
                    check("2026-08-05T01:00:00Z", "FAILURE"),
                ]
            }
        }
    }
    assert merge_scheduler.failed_status_checks(pr) == []
