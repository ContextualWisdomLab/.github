"""Exact historical coverage-only reviews require refresh, never approval."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.ci import opencode_review_receipt_gate as receipt
from scripts.ci import pr_review_merge_scheduler as scheduler

FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "opencode_legacy_coverage_review5301203359.json"
)


def actual_review():
    """Read the authenticated public GraphQL review without altering its body."""
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def review_pr(review):
    """Bind one review to its exact current PR head."""
    return {"headRefOid": review["commit"]["oid"], "reviews": {"nodes": [review]}}


@pytest.mark.parametrize("surface", ["receipt", "scheduler"])
def test_actual_legacy_review_is_refresh_only(surface):
    """Review 5301203359 is non-substantive on both consumers, not an approval."""
    review = actual_review()
    pr = review_pr(review)
    if surface == "receipt":
        found, reason = receipt.evaluate_receipts([review], pr["headRefOid"])
        assert found is None
        assert "fallback changes request" in reason
    else:
        assert scheduler.current_head_coverage_change_request(pr) is True
        assert scheduler.has_current_head_approval(pr) is False


@pytest.mark.parametrize(
    "mutation",
    [
        "commit",
        "body_sha",
        "actor",
        "extra",
        "mixed",
        "unknown",
        "run_zero",
        "run_text",
        "attempt_zero",
        "attempt_text",
        "graph_finding",
        "graph_label",
        "path_role",
        "missing_map",
        "missing_identity",
        "duplicate_identity",
        "no_paths",
        "traversal",
        "absolute",
        "double_slash",
        "dot_path",
        "too_many_paths",
        "malformed_author",
        "malformed_commit",
        "state",
        "head",
        "missing_commit",
        "coverage_markers",
        "coverage_success",
    ],
)
def test_unknown_or_mixed_legacy_review_stays_blocking(mutation):
    """No substring, malformed identity, or arbitrary graph can authorize refresh."""
    from scripts.ci.opencode_legacy_coverage_fallback import (
        is_legacy_coverage_only_review,
    )

    review = actual_review()
    head = review["commit"]["oid"]
    body = review["body"]
    if mutation == "commit":
        review["commit"]["oid"] = "b" * 40
    elif mutation == "body_sha":
        body = body.replace(head, "b" * 40)
    elif mutation == "actor":
        review["author"]["login"] = "github-actions[bot]"
    elif mutation == "extra":
        body += "\nThe changed endpoint allows anonymous writes."
    elif mutation == "mixed":
        body = body.replace(
            "## Findings\n\n", "## Findings\n\n### HIGH Missing authorization\n"
        )
    elif mutation == "unknown":
        body = body.replace("## Changed behavior", "## Unknown behavior")
    elif mutation.startswith("run_"):
        body = body.replace(
            "Workflow run: 35908696823",
            "Workflow run: " + ("0" if mutation == "run_zero" else "not-a-run"),
        )
    elif mutation.startswith("attempt_"):
        body = body.replace(
            "Workflow attempt: 1",
            "Workflow attempt: " + ("0" if mutation == "attempt_zero" else "1.0"),
        )
    elif mutation == "graph_finding":
        body = body.replace(
            "flowchart LR\n",
            "flowchart LR\n  Missing authorization allows anonymous writes\n",
        )
    elif mutation == "graph_label":
        body = body.replace('I1["regression suite"]', 'I1["anonymous writes"]')
    elif mutation == "path_role":
        body = body.replace("` — regression suite", "` — anonymous writes")
    elif mutation == "missing_map":
        body = body.split("\n\n## Changed-File Evidence Map")[0]
    elif mutation == "missing_identity":
        body = body.replace(f"- Head SHA: `{head}`\n", "")
    elif mutation == "duplicate_identity":
        start = body.index("- Head SHA:")
        end = body.index("\n\n## Review outcome")
        body += "\n" + body[start:end] + "\n"
    elif mutation == "no_paths":
        body = body.replace(
            "- `services/analysis-engine/tests/test_supply_chain_policy.py` — regression suite\n",
            "",
        )
    elif mutation in {"traversal", "absolute", "double_slash", "dot_path"}:
        path = {
            "traversal": "../tests/test_policy.py",
            "absolute": "/tests/test_policy.py",
            "double_slash": "tests//test_policy.py",
            "dot_path": "./tests/test_policy.py",
        }[mutation]
        body = body.replace(
            "services/analysis-engine/tests/test_supply_chain_policy.py", path
        )
    elif mutation == "too_many_paths":
        body = body.replace(
            "## Changed files\n\n",
            "## Changed files\n\n"
            + "- `tests/test_extra.py` — regression suite\n" * 200,
        )
    elif mutation == "malformed_author":
        review["author"] = "unknown"
    elif mutation == "malformed_commit":
        review["commit"] = "unknown"
    elif mutation == "state":
        review["state"] = "PENDING"
    elif mutation == "head":
        head = "short"
    elif mutation == "missing_commit":
        review.pop("commit")
    elif mutation == "coverage_markers":
        body = "## Pull request overview\ncoverage evidence did not pass; coverage-evidence; required test/docstring evidence"
    else:
        body = body.replace("Coverage gate: `failure`", "Coverage gate: `success`")
    review["body"] = body
    assert is_legacy_coverage_only_review(review, head) is False
    pr = {"headRefOid": head, "reviews": {"nodes": [review]}}
    # Malformed API object shape is tested at the shared trust boundary; the
    # scheduler API contract itself still requires GraphQL mapping-shaped nodes.
    if mutation not in {"malformed_author", "malformed_commit"}:
        assert scheduler.current_head_coverage_change_request(pr) is False
    if mutation in {
        "extra",
        "mixed",
        "unknown",
        "run_zero",
        "run_text",
        "attempt_zero",
        "attempt_text",
        "graph_finding",
        "graph_label",
        "path_role",
        "missing_map",
        "missing_identity",
        "duplicate_identity",
        "no_paths",
        "traversal",
        "absolute",
        "double_slash",
        "dot_path",
        "too_many_paths",
        "coverage_markers",
        "coverage_success",
    }:
        assert receipt.evaluate_receipts([review], head)[0] is review


@pytest.mark.parametrize("state", ["CHANGES_REQUESTED", "APPROVED", "COMMENTED"])
def test_newer_fallback_never_resurrects_older_approval(state):
    """A canonical fallback cannot authorize approval even when misposted APPROVED."""
    review = actual_review()
    head = review["commit"]["oid"]
    older = {
        **review,
        "id": "older",
        "state": "APPROVED",
        "body": "## Pull request overview\nSubstantive review.",
    }
    review["state"] = state
    assert receipt.evaluate_receipts([older, review], head)[0] is None
    assert (
        scheduler.has_current_head_approval(
            {"headRefOid": head, "reviews": {"nodes": [older, review]}}
        )
        is False
    )


@pytest.mark.parametrize("login", ["opencode-agent", "opencode-agent[bot]"])
@pytest.mark.parametrize("merge_state", ["UNKNOWN", "DIRTY"])
def test_rest_and_canonical_graph_variants(login, merge_state):
    """Exact reconstruction is generic in repository, paths, head, run, and attempt."""
    from scripts.ci.opencode_review_surfaces import build_fallback_review, emit_mermaid
    from scripts.ci.opencode_legacy_coverage_fallback import (
        is_legacy_coverage_only_review,
    )

    head = "a" * 40
    paths = ["backend/api.py", "frontend/view.tsx", "tests/test_api.py"]
    body = build_fallback_review(
        changed_files=paths,
        head_sha=head,
        run_id="99",
        run_attempt="3",
        coverage_result="failure",
    )
    body += "\n## Review outcome\n\nCoverage is a gate, not the review. This body reviews the changed product files."
    body += "\n\n## Changed-File Evidence Map\n\n" + emit_mermaid(
        paths, merge_state=merge_state
    )
    review = {
        "id": 1,
        "user": {"login": login},
        "commit_id": head,
        "state": "CHANGES_REQUESTED",
        "body": body,
    }
    assert is_legacy_coverage_only_review(review, head) is True
    assert receipt.evaluate_receipts([review], head)[0] is None


def test_producer_rejection_stays_a_formal_blocker():
    """A normalized path that violates producer anchor policy cannot crash the gate."""
    from scripts.ci.opencode_legacy_coverage_fallback import (
        is_legacy_coverage_only_review,
    )

    review = actual_review()
    head = review["commit"]["oid"]
    review["body"] = review["body"].replace(
        "services/analysis-engine/tests/test_supply_chain_policy.py",
        "docs/.github/workflows/opencode-review.yml",
    )
    assert is_legacy_coverage_only_review(review, head) is False
    assert receipt.evaluate_receipts([review], head)[0] is review


def test_direct_script_imports_fail_closed(monkeypatch):
    """Direct CLI loading uses the same classifier without package import paths."""
    import builtins
    import importlib
    import sys

    original = builtins.__import__

    def direct_import(name, *args, **kwargs):
        """Exercise direct-script fallback imports with no package namespace."""
        if name.startswith("scripts.ci.opencode_"):
            raise ModuleNotFoundError(name)
        return original(name, *args, **kwargs)

    from scripts.ci import opencode_legacy_coverage_fallback as classifier
    from scripts.ci import opencode_review_surfaces as surfaces

    with monkeypatch.context() as context:
        context.syspath_prepend(str(Path("scripts/ci").resolve()))
        context.setitem(sys.modules, "opencode_review_surfaces", surfaces)
        context.setitem(sys.modules, "opencode_legacy_coverage_fallback", classifier)
        context.setattr(builtins, "__import__", direct_import)
        importlib.reload(classifier)
        importlib.reload(receipt)
        review = actual_review()
        head = review["commit"]["oid"]
        assert classifier.is_legacy_coverage_only_review(review, head)
        assert receipt.evaluate_receipts([review], head)[0] is None
    importlib.reload(classifier)
    importlib.reload(receipt)


@pytest.mark.parametrize("peer", ["CodeQL", "strix", "coverage-evidence"])
@pytest.mark.parametrize("conclusion", ["FAILURE", "CANCELLED", "TIMED_OUT"])
def test_actual_legacy_failed_peer_never_dispatches_or_merges(
    monkeypatch, peer, conclusion
):
    """Actual fallback plus any failed peer must retain WAIT/BLOCK, no mutations."""
    review = actual_review()
    head = review["commit"]["oid"]
    checks = [
        {
            "__typename": "CheckRun",
            "name": name,
            "status": "COMPLETED",
            "conclusion": conclusion if name == peer else "SUCCESS",
        }
        for name in ("coverage-evidence", "strix", "CodeQL")
    ]
    pr = {
        **review_pr(review),
        "number": 1176,
        "isDraft": False,
        "mergeable": "MERGEABLE",
        "mergeStateStatus": "CLEAN",
        "baseRefName": "main",
        "baseRefOid": "b" * 40,
        "headRefName": "feature",
        "headRepository": {"nameWithOwner": "owner/repo"},
        "author": {"login": "pull-request-author"},
        "reviewDecision": "CHANGES_REQUESTED",
        "reviewThreads": {"nodes": []},
        "statusCheckRollup": {"contexts": {"nodes": checks}},
        "commits": {"nodes": [{"commit": {"oid": head}}]},
    }

    def forbidden(*args, **kwargs):
        """Fail the test before any live dispatch, merge, or other GitHub mutation."""
        raise AssertionError("mutation not authorized by fallback")

    for name in (
        "dispatch_opencode_review",
        "dispatch_strix_evidence",
        "merge_pr",
        "enable_auto_merge",
        "run",
        "run_github_dispatch",
        "run_github_actions",
    ):
        monkeypatch.setattr(scheduler, name, forbidden)
    decision = scheduler.inspect_pr(
        "owner/repo",
        pr,
        dry_run=True,
        trigger_reviews=True,
        enable_auto_merge_flag=True,
        update_branches=True,
        workflow="OpenCode Review",
        security_workflow="Strix Security Scan",
        base_branch="main",
        merge_mode="auto",
    )
    assert decision.action in {"block", "wait"}
    assert scheduler.contract_decision(decision) not in {
        "MERGE",
        "AUTO_MERGE",
        "REVIEW_DISPATCH",
    }
    assert not scheduler.has_current_head_approval(pr)


def test_substantive_review_after_legacy_still_deduplicates():
    """Fresh actual source findings remain formal blockers after an old fallback."""
    review = actual_review()
    head = review["commit"]["oid"]
    substantive = {
        **review,
        "id": "newer",
        "body": "## Pull request overview\n## Findings\n### HIGH Missing authorization\nAnonymous writes.",
    }
    assert receipt.evaluate_receipts([review, substantive], head)[0] is substantive
    assert (
        scheduler.current_head_coverage_change_request(
            {"headRefOid": head, "reviews": {"nodes": [review, substantive]}}
        )
        is False
    )


def test_existing_scheduler_protection_summary_boundaries():
    """Conflict and last-push guidance remain blockers, never refresh authority."""
    assert scheduler.is_strix_scan_check_run(
        {"__typename": "CheckRun", "name": "strix"}
    )
    assert not scheduler.is_strix_scan_check_run(
        {"__typename": "StatusContext", "name": "strix"}
    )
    assert "reviewDecision is REVIEW_REQUIRED" in scheduler.auto_merge_wait_reason(
        "BLOCKED", {"reviewDecision": "REVIEW_REQUIRED"}
    )
    conflict = scheduler.Decision(
        1,
        "block",
        "merge conflict: DIRTY; base=main, head=feature; resolve conflict markers",
    )
    assert scheduler.conflict_repair_summary([conflict])
    restamp = scheduler.Decision(
        1,
        "restamp_head",
        "last-push approval head refresh created same-tree head ffffffffffff",
        ("unrelated note",),
    )
    assert scheduler.last_push_approval_restamp_summary([restamp])
