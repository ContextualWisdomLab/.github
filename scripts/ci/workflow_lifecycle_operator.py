#!/usr/bin/env python3
"""Reviewed write primitives for confirmed workflow-lifecycle findings."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from scripts.ci.inventory_orphaned_workflows import (
    HEX_SHA256,
    REPO_SLUG,
    GitHubTransport,
    InventoryError,
    assert_default_branch_bound,
    owner_issue_for,
)


def disable_confirmed_orphan(
    client: GitHubTransport,
    record: Mapping[str, Any],
    *,
    confirmed_head_sha: str,
) -> None:
    """Disable one reviewed ledger orphan after a fresh exact-head check."""
    if record.get("classification") != "orphan_active":
        raise InventoryError("operator may disable only a ledger orphan_active record")
    repository = record.get("repository")
    workflow_id = record.get("workflow_id")
    ledger_sha = record.get("default_branch_sha")
    if not isinstance(repository, str) or not isinstance(workflow_id, int):
        raise InventoryError("operator record identity is malformed")
    assert_default_branch_bound(ledger_sha, confirmed_head_sha)
    try:
        client.request(
            f"/repos/ContextualWisdomLab/{repository}/actions/workflows/{workflow_id}/disable",
            method="PUT",
        )
    except Exception as exc:
        raise InventoryError(
            f"operator disable failed closed: {type(exc).__name__}"
        ) from exc


def publish_owner_issue(
    client: GitHubTransport,
    record: Mapping[str, Any],
    *,
    ledger_sha256: str,
) -> str:
    """Create or update the bounded owner issue for one confirmed orphan."""
    if (
        record.get("classification") != "orphan_active"
        or HEX_SHA256.fullmatch(ledger_sha256) is None
    ):
        raise InventoryError(
            "issue publication requires an orphan_active and ledger digest"
        )
    repository = record.get("repository")
    if not isinstance(repository, str) or REPO_SLUG.fullmatch(repository) is None:
        raise InventoryError("issue publication repository is malformed")
    issue = owner_issue_for(repository)
    body = (
        "<!-- cwl-workflow-lifecycle -->\n"
        f"Exact workflow registry evidence: `{record.get('workflow_id')}` / "
        f"`{record.get('path')}` at `{record.get('default_branch_sha')}`.\n"
        f"Ledger SHA-256: `{ledger_sha256}`.\n"
    )
    try:
        if issue is not None:
            number = issue.rsplit("#", 1)[1]
            client.request(
                f"/repos/ContextualWisdomLab/{repository}/issues/{number}/comments",
                method="POST",
                payload={"body": body},
            )
            return issue
        created = client.request(
            f"/repos/ContextualWisdomLab/{repository}/issues",
            method="POST",
            payload={
                "title": "Disable orphaned workflow registry identity",
                "body": body,
            },
        )
    except Exception as exc:
        raise InventoryError(
            f"owner issue publication failed closed: {type(exc).__name__}"
        ) from exc
    number = created.get("number") if isinstance(created, Mapping) else None
    if not isinstance(number, int) or number <= 0:
        raise InventoryError("owner issue creation returned no issue number")
    return f"ContextualWisdomLab/{repository}#{number}"
