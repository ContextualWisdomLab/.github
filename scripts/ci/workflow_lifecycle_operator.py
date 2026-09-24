"""Reviewed owner-issue publication for workflow-lifecycle findings."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import quote

from scripts.ci.inventory_orphaned_workflows import (
    CAPABILITY,
    HEX_SHA256,
    MAX_PAGES,
    REPO_SLUG,
    GitHubTransport,
    InventoryError,
    assert_default_branch_bound,
    classify_workflow,
    is_exact_sha,
    is_repository_workflow_path,
    owner_issue_for,
    reject_duplicate_keys,
    write_ledger,
)

MAX_LEDGER_BYTES = 16_777_216


def reject_non_json_constant(value: str) -> None:
    """Refuse non-standard JSON numbers in reviewed evidence."""
    raise InventoryError(f"non-JSON ledger constant {value}")


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
    workflow_id = record.get("workflow_id")
    path = record.get("path")
    sha = record.get("default_branch_sha")
    if (
        not isinstance(workflow_id, int)
        or isinstance(workflow_id, bool)
        or workflow_id <= 0
        or not isinstance(path, str)
        or not is_repository_workflow_path(path)
        or not is_exact_sha(sha)
    ):
        raise InventoryError("issue publication workflow evidence is malformed")
    issue = owner_issue_for(repository)
    try:
        repo_path = f"/repos/ContextualWisdomLab/{repository}"
        repo = client.request(repo_path)
        if (
            not isinstance(repo, Mapping)
            or repo.get("full_name") != f"ContextualWisdomLab/{repository}"
            or repo.get("archived") is not False
        ):
            raise InventoryError("owner repository identity changed")
        branch = repo.get("default_branch")
        if not isinstance(branch, str) or not branch:
            raise InventoryError("owner repository default branch is missing")
        commit_path = f"{repo_path}/commits/{quote(branch, safe='')}"
        start = client.request(commit_path)
        if not isinstance(start, Mapping) or start.get("sha") != sha:
            raise InventoryError("owner repository default branch moved")
        workflow = client.request(f"{repo_path}/actions/workflows/{workflow_id}")
        if (
            not isinstance(workflow, Mapping)
            or workflow.get("id") != workflow_id
            or workflow.get("path") != path
            or classify_workflow(
                path=path, state=workflow.get("state"), source_present=False
            )
            != "orphan_active"
        ):
            raise InventoryError("owner workflow identity changed")
        tree = client.request(f"{repo_path}/git/trees/{sha}?recursive=1")
        entries = tree.get("tree") if isinstance(tree, Mapping) else None
        if (
            not isinstance(tree, Mapping)
            or tree.get("truncated") is not False
            or not isinstance(entries, list)
            or any(
                not isinstance(item, Mapping)
                or not isinstance(item.get("path"), str)
                or item.get("type") not in {"blob", "tree", "commit"}
                for item in entries
            )
            or any(
                item.get("type") == "blob" and item.get("path") == path
                for item in entries
            )
        ):
            raise InventoryError("owner workflow source absence is unverified")
        end = client.request(commit_path)
        assert_default_branch_bound(
            sha, end.get("sha") if isinstance(end, Mapping) else None
        )
        body = (
            "<!-- cwl-workflow-lifecycle -->\n"
            f"Exact workflow registry evidence: `{workflow_id}` / "
            f"`{path}` at `{sha}`.\n"
            f"Ledger SHA-256: `{ledger_sha256}`.\n"
        )
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


def main(argv: Sequence[str] | None = None) -> int:
    """Publish one reviewed ledger finding after fresh live revalidation."""
    parser = argparse.ArgumentParser(description="Publish one workflow owner issue.")
    parser.add_argument("--ledger", required=True)
    parser.add_argument("--expected-ledger-sha256", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--workflow-id", type=int, required=True)
    args = parser.parse_args(argv)
    try:
        if HEX_SHA256.fullmatch(args.expected_ledger_sha256) is None:
            raise InventoryError("reviewed ledger SHA-256 is malformed")
        if REPO_SLUG.fullmatch(args.repository) is None or args.workflow_id <= 0:
            raise InventoryError("operator target is malformed")
        # ponytail: 16 MiB bounds parsing; raise only after measured fleet growth.
        with Path(args.ledger).open("rb") as source:
            raw = source.read(MAX_LEDGER_BYTES + 1)
        if not raw or len(raw) > MAX_LEDGER_BYTES:
            raise InventoryError("reviewed ledger is empty or exceeds 16 MiB")
        if hashlib.sha256(raw).hexdigest() != args.expected_ledger_sha256:
            raise InventoryError("reviewed ledger SHA-256 does not match")
        ledger = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=reject_non_json_constant,
        )
        if (
            not isinstance(ledger, dict)
            or ledger.get("schema_version") != "1"
            or ledger.get("capability") != CAPABILITY
            or ledger.get("organization") != "ContextualWisdomLab"
            or ledger.get("repository_inventory_complete") is not True
            or write_ledger(ledger, None).encode() != raw
        ):
            raise InventoryError(
                "reviewed ledger is not a canonical complete inventory"
            )
        records = ledger.get("records")
        if not isinstance(records, list):
            raise InventoryError("reviewed ledger has no records")
        matches = [
            item
            for item in records
            if isinstance(item, Mapping)
            and item.get("repository") == args.repository
            and item.get("workflow_id") == args.workflow_id
        ]
        if len(matches) != 1:
            raise InventoryError("reviewed ledger target is missing or ambiguous")
        from scripts.ci.organization_commercial_readiness_loop import GitHubClient

        try:
            client = GitHubClient.from_environment()
        except Exception as exc:
            raise InventoryError(
                f"operator credential unavailable: {type(exc).__name__}"
            ) from exc
        issue = publish_owner_issue(client, matches[0], ledger=ledger)
    except (InventoryError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        print(
            f"ERROR: owner issue publication refused: {type(exc).__name__}",
            file=sys.stderr,
        )
        return 2
    print(issue)
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through main()
    raise SystemExit(main())
