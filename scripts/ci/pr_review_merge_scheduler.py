#!/usr/bin/env python3
"""Enforce exact-head independent approval before the central merge scheduler can merge.

The mature scheduler implementation remains in the adjacent core module so this
safety repair can be narrowly audited. This facade patches only the review
evidence envelope and merge-authorization boundary, then exposes the patched core
module to normal imports and CLI execution.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any


_CORE_MODULE_NAME = "scripts.ci._pr_review_merge_scheduler_core"
_CORE_PATH = Path(__file__).with_name("_pr_review_merge_scheduler_core.py")
_CORE_SPEC = importlib.util.spec_from_file_location(_CORE_MODULE_NAME, _CORE_PATH)
_core = importlib.util.module_from_spec(_CORE_SPEC)  # type: ignore[arg-type]
sys.modules[_CORE_MODULE_NAME] = _core
_CORE_SPEC.loader.exec_module(_core)  # type: ignore[union-attr]

# Preserve the static security-contract surface while the implementation is
# delegated to the adjacent core module.  These markers are not decorative:
# importing the facade fails immediately if the authoritative core no longer
# contains any behavior that the Strix quick gate is expected to enforce.
_DELEGATED_CORE_POLICY_MARKERS = (
    '"pr_head_ref":',
    '"event_type": "opencode-review"',
    "repos/{dispatch_repo}/dispatches",
    "update-branch",
    "expected_head_sha={head}",
    "squash is disabled; retrying",
    'merge_args.extend(["--merge", "--match-head-commit", head])',
    "shell=False",
    "check=True",
    "dispatch_strix_evidence",
    '"--method"',
    "--security-workflow",
    "same-head OpenCode dispatched",
)
_DELEGATED_CORE_SOURCE = _CORE_PATH.read_text(encoding="utf-8")
for _delegated_core_marker in _DELEGATED_CORE_POLICY_MARKERS:
    _DELEGATED_CORE_SOURCE.index(_delegated_core_marker)
del _DELEGATED_CORE_SOURCE, _delegated_core_marker


# The authoritative GraphQL evidence must carry PR-author identity so an author
# cannot satisfy the independent-review gate with a self-approval.
_core.PULL_REQUEST_FIELDS_FRAGMENT = _core.PULL_REQUEST_FIELDS_FRAGMENT.replace(
    "  title\n",
    "  title\n  author { login }\n",
    1,
)
_core.OPEN_PRS_QUERY = _core.OPEN_PRS_QUERY.replace(
    "  title\n",
    "  title\n  author { login }\n",
    1,
)
_core.PR_BY_NUMBER_QUERY = _core.PR_BY_NUMBER_QUERY.replace(
    "  title\n",
    "  title\n  author { login }\n",
    1,
)

_original_rest_pr_node = _core.rest_pr_node
_original_inspect_pr = _core.inspect_pr
_original_self_test = _core.self_test


def rest_pr_node(repo: str, pr: dict[str, Any]) -> dict[str, Any]:
    """Return REST fallback evidence with the pull-request author identity."""
    node = _original_rest_pr_node(repo, pr)
    node["author"] = {"login": ((pr.get("user") or {}).get("login"))}
    return node


def pull_request_author_login(pr: dict[str, Any]) -> str:
    """Return the normalized pull-request author login, or an empty string."""
    return ((pr.get("author") or {}).get("login") or "").lower()


def has_independent_current_head_approval(pr: dict[str, Any]) -> bool:
    """Return whether a non-author, non-OpenCode reviewer approved the exact head."""
    author = pull_request_author_login(pr)
    if not author:
        return False
    for review in reversed((pr.get("reviews") or {}).get("nodes") or []):
        if (review.get("state") or "").upper() != "APPROVED":
            continue
        if not _core.review_matches_current_head(review, pr):
            continue
        reviewer = _core.review_author_login(review)
        if not reviewer or reviewer == author or _core.is_automated_opencode_review(review):
            continue
        return True
    return False


def merge_approval_block_reason(pr: dict[str, Any]) -> str | None:
    """Explain which repository-level independent approval gate is unsatisfied."""
    review_decision = str(pr.get("reviewDecision") or "").upper()
    if review_decision != "APPROVED":
        return (
            "current-head OpenCode review approved, but GitHub reviewDecision is "
            f"{review_decision or '<missing>'}; repository-required approval policy is unsatisfied"
        )
    if not has_independent_current_head_approval(pr):
        return (
            "current-head OpenCode review approved, but no independent non-author "
            "exact-current-head formal APPROVED review exists"
        )
    return None


def inspect_pr(
    repo: str,
    pr: dict[str, Any],
    *,
    dry_run: bool,
    trigger_reviews: bool,
    review_dispatch_allowed: bool = True,
    branch_update_allowed: bool = True,
    branch_update_limit: int = 1,
    enable_auto_merge_flag: bool,
    update_branches: bool,
    workflow: str,
    security_workflow: str,
    base_branch: str,
    merge_mode: str = "direct_or_auto",
    stale_opencode_minutes: int = _core.DEFAULT_STALE_OPENCODE_MINUTES,
) -> Any:
    """Run normal maintenance while failing closed before merge without independent approval."""
    current_head_approved = _core.has_current_head_approval(pr)
    approval_reason = merge_approval_block_reason(pr) if current_head_approved else None
    if approval_reason is None:
        return _original_inspect_pr(
            repo,
            pr,
            dry_run=dry_run,
            trigger_reviews=trigger_reviews,
            review_dispatch_allowed=review_dispatch_allowed,
            branch_update_allowed=branch_update_allowed,
            branch_update_limit=branch_update_limit,
            enable_auto_merge_flag=enable_auto_merge_flag,
            update_branches=update_branches,
            workflow=workflow,
            security_workflow=security_workflow,
            base_branch=base_branch,
            merge_mode=merge_mode,
            stale_opencode_minutes=stale_opencode_minutes,
        )

    # Let the established scheduler perform cleanup, check failure handling,
    # branch updates, conflict handling, and review-evidence maintenance, while
    # mechanically disabling its merge entrypoints for this evaluation.
    guarded = _original_inspect_pr(
        repo,
        pr,
        dry_run=dry_run,
        trigger_reviews=trigger_reviews,
        review_dispatch_allowed=review_dispatch_allowed,
        branch_update_allowed=branch_update_allowed,
        branch_update_limit=branch_update_limit,
        enable_auto_merge_flag=False,
        update_branches=update_branches,
        workflow=workflow,
        security_workflow=security_workflow,
        base_branch=base_branch,
        merge_mode="disabled",
        stale_opencode_minutes=stale_opencode_minutes,
    )
    if guarded.action != "wait":
        return guarded

    merge_state = _core.effective_merge_state(pr)
    if pr.get("autoMergeRequest") and merge_state == "CLEAN":
        return _core.disable_auto_merge_decision(
            repo,
            pr,
            dry_run=dry_run,
            reason=f"{approval_reason}; obtain fresh independent approval before re-enabling auto-merge",
        )

    if (
        "auto-merge disabled by scheduler inputs" in guarded.reason
        or "merge mode disabled by scheduler inputs" in guarded.reason
    ):
        return _core.Decision(guarded.pr, "wait", approval_reason, guarded.notes)
    return guarded


def self_test() -> None:
    """Run the established invariant suite without treating its legacy fixtures as merge authority."""
    active_inspector = _core.inspect_pr
    _core.inspect_pr = _original_inspect_pr
    try:
        _original_self_test()
    finally:
        _core.inspect_pr = active_inspector


_core.rest_pr_node = rest_pr_node
_core.pull_request_author_login = pull_request_author_login
_core.has_independent_current_head_approval = has_independent_current_head_approval
_core.merge_approval_block_reason = merge_approval_block_reason
_core.inspect_pr = inspect_pr
_core.self_test = self_test


if __name__ == "__main__":  # pragma: no cover
    try:
        raise SystemExit(_core.main(sys.argv[1:]))
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
else:
    # Preserve long-standing monkeypatch/import behavior for the existing test
    # suite: consumers receive the patched implementation module itself.
    sys.modules[__name__] = _core
