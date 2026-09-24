"""Reviewed owner-issue publication for workflow-lifecycle findings."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any

from scripts.ci.inventory_orphaned_workflows import (
    MAX_PAGES,
    REPO_SLUG,
    GitHubTransport,
    InventoryError,
    owner_issue_for,
    write_ledger,
)


def publish_owner_issue(
    client: GitHubTransport,
    record: Mapping[str, Any],
    *,
    ledger: Mapping[str, Any],
) -> str:
    """Create or update the bounded owner issue for one confirmed orphan."""
    records = ledger.get("records")
    if (
        record.get("classification") != "orphan_active"
        or not isinstance(records, list)
        or record not in records
    ):
        raise InventoryError("issue publication requires a ledger-bound orphan_active")
    ledger_sha256 = hashlib.sha256(write_ledger(ledger, None).encode()).hexdigest()
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
        marker = "<!-- cwl-workflow-lifecycle -->"
        page = 1
        matches: list[Mapping[str, Any]] = []
        while True:
            existing = client.request(
                f"/repos/ContextualWisdomLab/{repository}/issues?state=all&per_page=100&page={page}"
            )
            if not isinstance(existing, list):
                raise InventoryError("owner issue inventory is incomplete")
            matches.extend(
                item
                for item in existing
                if isinstance(item, Mapping)
                and marker in str(item.get("body") or "")
                and "pull_request" not in item
            )
            if len(existing) < 100:
                break
            page += 1
            if page > MAX_PAGES:
                raise InventoryError("owner issue pagination exceeded limit")
        if matches:
            number = matches[0].get("number")
            if not isinstance(number, int) or number <= 0 or len(matches) != 1:
                raise InventoryError("owner issue identity is ambiguous")
            if matches[0].get("state") != "open":
                raise InventoryError(
                    "owner issue is closed; operator review is required"
                )
            if f"Ledger SHA-256: `{ledger_sha256}`" not in str(
                matches[0].get("body") or ""
            ):
                client.request(
                    f"/repos/ContextualWisdomLab/{repository}/issues/{number}/comments",
                    method="POST",
                    payload={"body": body},
                )
            return f"ContextualWisdomLab/{repository}#{number}"
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
