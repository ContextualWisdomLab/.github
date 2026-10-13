"""Recognize only authenticated exact-head Noema App review receipts."""

from __future__ import annotations

import json
from copy import deepcopy

import pytest

from scripts.ci import noema_review_gate as publisher
from scripts.ci import pr_review_merge_scheduler_core as scheduler

HEAD = "a" * 40
BASE = "b" * 40


@pytest.fixture
def published_review(monkeypatch: pytest.MonkeyPatch) -> dict:
    """Capture the real publisher without a network write or model call."""
    payloads = []

    def capture(_args, *, stdin=None):
        payloads.append(json.loads(stdin))
        return ""

    monkeypatch.setattr(publisher, "run", capture)
    monkeypatch.setenv("NOEMA_REVIEW_TOKEN_SOURCE", "noema-review-github-app-refresh")
    publisher.submit_review(
        "ContextualWisdomLab/example", 7,
        {"headRefOid": HEAD, "baseRefOid": BASE}, "cwl-noema-review[bot]",
        {
            "decision": "approve", "summary": "Changed-line review found no blocking regression.",
            "findings": [],
            "reviewed_lines": [{"path": "src/runtime.py", "line": 12, "side": "RIGHT", "analysis": "Invalid references are rejected before lookup."}],
            "adversarial_validation": {
                "status": "passed", "residual_risk": "Deployment evidence remains separate.",
                "probes": [{"path": "src/runtime.py", "line": 12, "side": "RIGHT", "outcome": "falsified", "hypothesis": "Invalid references reach lookup.", "evidence": "Fixture test at src/runtime.py:12 returned rejected input."}],
            },
        },
    )
    payload = payloads[0]
    assert payload["commit_id"] == HEAD and payload["event"] == "APPROVE"
    return scheduler.rest_review_node({"id": 17, "state": "APPROVED", "commit_id": HEAD, "user": {"login": "cwl-noema-review[bot]"}, "body": payload["body"]})


def pull_request(reviews: list[dict], *, author="participant") -> dict:
    """Build an authenticated API snapshot; independent gates retain their authority."""
    return {"author": {"login": author}, "headRefOid": HEAD, "baseRefOid": BASE, "reviewDecision": "APPROVED", "reviews": {"nodes": reviews}}


@pytest.mark.parametrize("api_type,eligible", [("Bot", True), ("User", False)])
def test_rest_conversion_preserves_authenticated_actor_type(published_review, api_type, eligible):
    """Conversion must not turn an explicit REST User into an App by suffix."""
    converted = scheduler.rest_review_node({
        "id": 18,
        "state": "APPROVED",
        "commit_id": HEAD,
        "user": {"login": "cwl-noema-review[bot]", "type": api_type},
        "body": published_review["body"],
    })
    assert converted["author"]["__typename"] == api_type
    assert scheduler.has_independent_current_head_approval(pull_request([converted])) is eligible


@pytest.mark.parametrize("graphql_actor", [False, True])
def test_actual_publisher_receipt_counts_as_independent_review(published_review, graphql_actor):
    if graphql_actor:
        published_review["author"] = {"login": "cwl-noema-review", "__typename": "Bot"}
    pr = pull_request([published_review])
    assert scheduler.has_independent_current_head_approval(pr)
    assert scheduler.merge_approval_block_reason(pr) is None


@pytest.mark.parametrize("source", ["noema-review-github-app"])
def test_authenticated_app_credential_sources(published_review, source):
    published_review["body"] = published_review["body"].replace("noema-review-github-app-refresh", source)
    assert scheduler.has_independent_current_head_approval(pull_request([published_review]))


@pytest.mark.parametrize("author", ["cwl-noema-review", "cwl-noema-review[bot]", "CWL-NOEMA-REVIEW"])
def test_app_never_approves_itself(published_review, author):
    assert not scheduler.has_independent_current_head_approval(pull_request([published_review], author=author))


@pytest.mark.parametrize("actor", [
    {"login": "cwl-noema-review", "__typename": "User"},
    {"login": "cwl-noema-review"},
    {"login": "cwl-noema-review[bot]", "__typename": "User"},
    {"login": "another-bot[bot]", "__typename": "Bot"},
    {"login": "opencode-agent[bot]", "__typename": "Bot"},
])
def test_only_canonical_authenticated_bot_qualifies(published_review, actor):
    published_review["author"] = actor
    assert not scheduler.has_independent_current_head_approval(pull_request([published_review]))


@pytest.mark.parametrize("commit", [None, {"oid": "b" * 40}, {"oid": "A" * 40}, {"oid": "short"}])
def test_body_head_never_replaces_actual_exact_commit(published_review, commit):
    published_review["commit"] = commit
    assert not scheduler.has_independent_current_head_approval(pull_request([published_review]))


@pytest.mark.parametrize("old,new", [
    (f"- Head SHA: `{HEAD}`", f"- Head SHA: `{'b' * 40}`"),
    ("decision=approve", "decision=comment"),
    ("- Result: APPROVE", "- Result: COMMENT"),
    ("- Actor: `cwl-noema-review[bot]`", "- Actor: `opencode-agent[bot]`"),
    ("noema-review-github-app-refresh", "noema-review-pat"),
    (publisher.NOEMA_REVIEW_FOOTER_MARKER, ""),
])
def test_incoherent_or_incomplete_receipt_fails_closed(published_review, old, new):
    published_review["body"] = published_review["body"].replace(old, new)
    assert not scheduler.has_independent_current_head_approval(pull_request([published_review]))


@pytest.mark.parametrize("state", ["CHANGES_REQUESTED", "DISMISSED", "APPROVED"])
def test_latest_formal_policy_state_blocks_old_approval(published_review, state):
    latest = deepcopy(published_review)
    latest.update(state=state, body="Malformed receipt.", author={"login": "cwl-noema-review", "__typename": "Bot"})
    assert not scheduler.has_independent_current_head_approval(pull_request([published_review, latest]))


@pytest.mark.parametrize("head", ["", "short", "A" * 40])
def test_noncanonical_snapshot_head_cannot_authorize_app_review(published_review, head):
    pr = pull_request([published_review])
    pr["headRefOid"] = head
    assert not scheduler.has_independent_current_head_approval(pr)


@pytest.mark.parametrize("mutation", ["missing_commit", "stale_commit", "wrong_api_type", "trailing_text", "duplicate_footer"])
def test_latest_invalid_formal_receipt_never_falls_back(published_review, mutation):
    latest = deepcopy(published_review)
    if mutation == "missing_commit":
        latest["commit"] = None
    elif mutation == "stale_commit":
        latest["commit"] = {"oid": "b" * 40}
    elif mutation == "wrong_api_type":
        latest["author"] = {"login": "cwl-noema-review", "__typename": "User"}
    elif mutation == "trailing_text":
        latest["body"] += "\nUntrusted continuation."
    else:
        latest["body"] += publisher.NOEMA_REVIEW_FOOTER_MARKER
    assert not scheduler.has_independent_current_head_approval(pull_request([published_review, latest]))


def test_comment_does_not_revoke_formal_approval(published_review):
    latest = deepcopy(published_review)
    latest.update(state="COMMENTED", body="Additional observation.")
    assert scheduler.has_independent_current_head_approval(pull_request([published_review, latest]))


def test_github_review_decision_remains_required(published_review):
    pr = pull_request([published_review])
    pr["reviewDecision"] = "REVIEW_REQUIRED"
    assert "repository approval policy is unsatisfied" in scheduler.merge_approval_block_reason(pr)


def test_human_approval_behavior_is_unchanged():
    review = {"state": "APPROVED", "author": {"login": "reviewer", "__typename": "User"}, "commit": {"oid": HEAD}}
    assert scheduler.has_independent_current_head_approval(pull_request([review]))
