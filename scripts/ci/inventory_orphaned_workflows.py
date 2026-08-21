#!/usr/bin/env python3
"""Read-only GitHub Actions workflow-lifecycle inventory.

The classifier answers whether an advertised workflow identity still has
source on the exact protected default-branch SHA. It never disables,
deletes, or recreates workflows and never reads ``COPILOT_GITHUB_TOKEN``.
CSAP and SOC 2 appear only as design constraints.

See ContextualWisdomLab/.github#945.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any, Callable


SCHEMA_VERSION = "1"
CAPABILITY = "workflow_lifecycle_inventory"
MAX_PAYLOAD_BYTES = 1_048_576
PER_PAGE_DEFAULT = 100
HEX_SHA = re.compile(r"^[0-9a-f]{40}$")
REPO_SLUG = re.compile(r"^[A-Za-z0-9._-]+$")
REPO_WORKFLOW_NAME = re.compile(r"^[^/]+\.(yml|yaml)$")
DYNAMIC_PREFIXES = ("dynamic/",)
DISABLED_STATES = frozenset(
    {
        "disabled_manually",
        "disabled_inactivity",
        "disabled_fork",
        "deleted",
    }
)
ACTIVE_STATES = frozenset({"active"})
CLASSIFICATIONS = (
    "present_active",
    "present_disabled",
    "orphan_active",
    "orphan_disabled",
    "dynamic_owned",
    "unresolved",
)
KNOWN_OWNER_ISSUES = {
    "appguardrail": "ContextualWisdomLab/appguardrail#929",
    "bandscope": "ContextualWisdomLab/bandscope#847",
    "clearfolio": "ContextualWisdomLab/clearfolio#423",
    "codec-carver": "ContextualWisdomLab/codec-carver#401",
    "contextual-orchestrator": "ContextualWisdomLab/contextual-orchestrator#122",
    "DiagramWeave": "ContextualWisdomLab/DiagramWeave#27",
    "disksage": "ContextualWisdomLab/disksage#191",
    "EgressWeave": "ContextualWisdomLab/EgressWeave#202",
    "fast-mlsirm": "ContextualWisdomLab/fast-mlsirm#809",
    "four-pillars": "ContextualWisdomLab/four-pillars#33",
    "inkspan": "ContextualWisdomLab/inkspan#278",
    "keyverse": "ContextualWisdomLab/keyverse#99",
    "naruon": "ContextualWisdomLab/naruon#1324",
    "newsdom-api": "ContextualWisdomLab/newsdom-api#604",
    "noema": "ContextualWisdomLab/noema#226",
    "OriginWeave": "ContextualWisdomLab/OriginWeave#123",
    "pg-erd-cloud": "ContextualWisdomLab/pg-erd-cloud#865",
    "RankWeave": "ContextualWisdomLab/RankWeave#38",
    "saju-caldav": "ContextualWisdomLab/saju-caldav#33",
    "ThreadWeave": "ContextualWisdomLab/ThreadWeave#31",
}
FORBIDDEN_TOKENS = frozenset({"COPILOT_GITHUB_TOKEN"})


class InventoryError(ValueError):
    """Fail-closed defect in workflow-lifecycle evidence."""


def reject_forbidden_token(name: str) -> None:
    """Refuse GitHub Copilot tokens and other forbidden credentials."""
    if name in FORBIDDEN_TOKENS:
        raise InventoryError(f"{name} is forbidden for this inventory")


def refuse_registry_mutation(action: str) -> None:
    """Keep disablement on a separately reviewed operator path."""
    raise InventoryError(
        f"registry mutation {action!r} is out of scope for this scanner"
    )


def is_exact_sha(value: object) -> bool:
    """Return whether *value* is a 40-character lowercase hex SHA."""
    return isinstance(value, str) and HEX_SHA.fullmatch(value) is not None


def parse_link_has_next(link_header: object) -> bool:
    """Return whether a GitHub ``Link`` header advertises another page."""
    if link_header is None:
        return False
    if not isinstance(link_header, str) or not link_header.strip():
        raise InventoryError("Link header is malformed")
    return 'rel="next"' in link_header


def decode_registry_path(path: object) -> str:
    """Decode one percent-encoding pass and reject traversal disguises."""
    if not isinstance(path, str) or not path or "\x00" in path:
        raise InventoryError("workflow path is missing or NUL-bearing")
    if "\\" in path:
        raise InventoryError("workflow path must not contain backslashes")
    if "%" in path:
        raise InventoryError("workflow path must not be percent-encoded")
    parts = [part for part in path.split("/") if part not in {"", "."}]
    if ".." in parts:
        raise InventoryError("path traversal is not a workflow identity")
    return path


def is_dynamic_owned_path(path: str) -> bool:
    """Return whether *path* is a GitHub-owned dynamic workflow identity."""
    return path.startswith(DYNAMIC_PREFIXES)


def is_repository_workflow_path(path: str) -> bool:
    """Return whether *path* is an exact repository workflow file."""
    if not path.startswith(".github/workflows/"):
        return False
    name = path[len(".github/workflows/") :]
    return REPO_WORKFLOW_NAME.fullmatch(name) is not None


def interpret_status(status: int, *, resource: str) -> None:
    """Fail closed on incomplete visibility or transient upstream errors."""
    if status == 200:
        return
    if status in {401, 403}:
        raise InventoryError(f"permission loss for {resource}")
    if status == 404:
        raise InventoryError(f"missing visibility for {resource}")
    if status >= 500:
        raise InventoryError(f"transient upstream error {status} for {resource}")
    raise InventoryError(f"unexpected status {status} for {resource}")


def fetch_with_one_retry(
    fetch: Callable[[str], tuple[int, Any, Mapping[str, str]]],
    url: str,
) -> tuple[Any, Mapping[str, str]]:
    """GET JSON once, retry a 5xx exactly once, then fail closed."""
    status, body, headers = fetch(url)
    if status >= 500:
        status, body, headers = fetch(url)
    interpret_status(status, resource=url)
    return body, headers


def classify_workflow(
    *,
    path: str,
    state: object,
    source_present: bool | None,
) -> str:
    """Classify one registry identity against the bound default-branch tree."""
    if is_dynamic_owned_path(path):
        return "dynamic_owned"
    if not is_repository_workflow_path(path):
        return "unresolved"
    if source_present is None:
        return "unresolved"
    if state in ACTIVE_STATES:
        return "present_active" if source_present else "orphan_active"
    if state in DISABLED_STATES:
        return "present_disabled" if source_present else "orphan_disabled"
    return "unresolved"


def assert_unique_workflow_ids(workflows: Sequence[Mapping[str, Any]]) -> None:
    """Fail closed when a page set reuses a workflow id."""
    seen: set[int] = set()
    for workflow in workflows:
        workflow_id = workflow.get("id")
        if not isinstance(workflow_id, int) or workflow_id <= 0:
            raise InventoryError("workflow id must be a positive integer")
        if workflow_id in seen:
            raise InventoryError(f"reused workflow id {workflow_id}")
        seen.add(workflow_id)


def collect_workflow_pages(
    pages: Iterable[Mapping[str, Any]],
    *,
    per_page: int = PER_PAGE_DEFAULT,
) -> list[dict[str, Any]]:
    """Merge workflow pages and fail closed on truncation or count drift."""
    if per_page <= 0:
        raise InventoryError("per_page must be positive")
    collected: list[dict[str, Any]] = []
    expected_total: int | None = None
    saw_page = False
    open_next = False
    for page in pages:
        saw_page = True
        if not isinstance(page, Mapping):
            raise InventoryError("workflow page is not an object")
        workflows = page.get("workflows")
        total_count = page.get("total_count")
        if not isinstance(workflows, list):
            raise InventoryError("workflow page is missing a workflows array")
        if not isinstance(total_count, int) or total_count < 0:
            raise InventoryError("workflow page total_count is invalid")
        if expected_total is None:
            expected_total = total_count
        elif total_count != expected_total:
            raise InventoryError("workflow total_count drifted across pages")
        if len(workflows) > per_page:
            raise InventoryError("workflow page exceeds per_page")
        for workflow in workflows:
            if not isinstance(workflow, dict):
                raise InventoryError("workflow record is not an object")
        collected.extend(workflows)
        link_next = page.get("_link_next")
        if link_next is None:
            open_next = parse_link_has_next(page.get("link"))
        elif isinstance(link_next, bool):
            open_next = link_next
        else:
            raise InventoryError("workflow page _link_next must be boolean")
        if open_next and not workflows:
            raise InventoryError("empty workflow page advertised a next link")
        if not open_next:
            break
    else:
        if open_next:
            raise InventoryError("pagination truncated after last next link")
    if not saw_page:
        raise InventoryError("no workflow pages")
    if expected_total is None or len(collected) != expected_total:
        raise InventoryError("pagination truncated or incomplete")
    assert_unique_workflow_ids(collected)
    return collected


def assert_default_branch_bound(start_sha: object, end_sha: object) -> str:
    """Bind the inventory to one default-branch SHA or abort."""
    if not is_exact_sha(start_sha) or not is_exact_sha(end_sha):
        raise InventoryError("default-branch SHA is not a 40-character hex digest")
    if start_sha != end_sha:
        raise InventoryError("default-branch SHA moved during inventory")
    return str(start_sha)


def owner_issue_for(repository: str) -> str | None:
    """Return the known owning issue for a fleet repository, if any."""
    return KNOWN_OWNER_ISSUES.get(repository)


def inventory_repository(record: Mapping[str, Any]) -> dict[str, Any]:
    """Inventory one non-archived repository against its bound SHA."""
    name = record.get("name")
    if not isinstance(name, str) or REPO_SLUG.fullmatch(name) is None:
        raise InventoryError("repository name is not a valid slug")
    if record.get("archived") is True:
        return {
            "repository": name,
            "skipped": "archived",
            "records": [],
        }
    if record.get("archived") is not False:
        raise InventoryError(f"{name} archived flag is not boolean")
    sha = assert_default_branch_bound(
        record.get("default_branch_sha"),
        record.get("default_branch_sha_after"),
    )
    tree_paths = record.get("tree_paths")
    if not isinstance(tree_paths, list) or any(
        not isinstance(path, str) for path in tree_paths
    ):
        raise InventoryError(f"{name} tree_paths must be a list of strings")
    tree = set(tree_paths)
    pages = record.get("workflow_pages")
    if not isinstance(pages, list):
        raise InventoryError(f"{name} workflow_pages must be a list")
    workflows = collect_workflow_pages(pages)
    records: list[dict[str, Any]] = []
    for workflow in workflows:
        path = decode_registry_path(workflow.get("path"))
        source_present: bool | None
        if is_repository_workflow_path(path):
            source_present = path in tree
        elif is_dynamic_owned_path(path):
            source_present = None
        else:
            source_present = None
        classification = classify_workflow(
            path=path,
            state=workflow.get("state"),
            source_present=source_present,
        )
        item = {
            "repository": name,
            "workflow_id": workflow.get("id"),
            "name": workflow.get("name"),
            "path": path,
            "state": workflow.get("state"),
            "default_branch_sha": sha,
            "classification": classification,
        }
        if classification == "orphan_active":
            owner = owner_issue_for(name)
            if owner is not None:
                item["owner_issue"] = owner
        records.append(item)
    return {
        "repository": name,
        "default_branch": record.get("default_branch"),
        "default_branch_sha": sha,
        "page_count": len(pages),
        "workflow_count": len(records),
        "records": records,
    }


def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Build an object while rejecting duplicate JSON keys."""
    seen: set[str] = set()
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in seen:
            raise InventoryError(f"duplicate object key {key!r}")
        seen.add(key)
        result[key] = value
    return result


def load_payload_bytes(raw: bytes) -> dict[str, Any]:
    """Parse a bounded UTF-8 inventory payload and reject duplicate keys."""
    if not raw:
        raise InventoryError("payload is empty")
    if len(raw) > MAX_PAYLOAD_BYTES:
        raise InventoryError("payload exceeds 1048576 bytes")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InventoryError("payload is not UTF-8") from exc
    try:
        payload = json.loads(text, object_pairs_hook=reject_duplicate_keys)
    except json.JSONDecodeError as exc:
        raise InventoryError(f"payload is not JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise InventoryError("payload must be a JSON object")
    return payload


def inventory_organization(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Inventory every supplied repository and emit an immutable ledger."""
    organization = payload.get("organization")
    if organization != "ContextualWisdomLab":
        raise InventoryError("organization must be ContextualWisdomLab")
    observed_at = payload.get("observed_at")
    if not isinstance(observed_at, str) or not observed_at:
        raise InventoryError("observed_at is required")
    repositories = payload.get("repositories")
    if not isinstance(repositories, list) or not repositories:
        raise InventoryError("repositories must be a non-empty list")
    inventories: list[dict[str, Any]] = []
    for record in repositories:
        if not isinstance(record, Mapping):
            raise InventoryError("repository record is not an object")
        inventories.append(inventory_repository(record))
    records = [
        item
        for inventory in inventories
        for item in inventory.get("records", [])
    ]
    counts = {name: 0 for name in CLASSIFICATIONS}
    for item in records:
        classification = item["classification"]
        if classification not in counts:
            raise InventoryError(f"unknown classification {classification!r}")
        counts[classification] += 1
    return {
        "schema_version": SCHEMA_VERSION,
        "capability": CAPABILITY,
        "organization": organization,
        "observed_at": observed_at,
        "assurance_posture": {
            "csap": "design_constraint",
            "soc2": "design_constraint",
            "certification_claim": False,
            "operational_pii_mask": False,
        },
        "counts": counts,
        "repositories": inventories,
        "records": records,
    }


def write_ledger(ledger: Mapping[str, Any], output: Path | None) -> str:
    """Serialize the ledger as UTF-8 JSON with a trailing newline."""
    text = json.dumps(ledger, indent=2, sort_keys=True) + "\n"
    if output is not None:
        output.write_text(text, encoding="utf-8")
    return text


def main(argv: Sequence[str] | None = None) -> int:
    """Load a fixture payload, emit a ledger, and optionally fail on orphans."""
    parser = argparse.ArgumentParser(
        description="Classify GitHub Actions workflow registry identities."
    )
    parser.add_argument("--payload", required=True, help="JSON inventory fixture")
    parser.add_argument("--output", help="optional ledger output path")
    parser.add_argument(
        "--fail-on-orphan-active",
        action="store_true",
        help="exit 1 when any orphan_active identity is observed",
    )
    parser.add_argument(
        "--mutate",
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args(argv)
    if args.mutate:
        try:
            refuse_registry_mutation(args.mutate)
        except InventoryError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
    try:
        raw = Path(args.payload).read_bytes()
        payload = load_payload_bytes(raw)
        ledger = inventory_organization(payload)
    except FileNotFoundError as exc:
        print(f"ERROR: payload not found: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"ERROR: unable to read payload: {exc}", file=sys.stderr)
        return 2
    except InventoryError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    try:
        text = write_ledger(ledger, Path(args.output) if args.output else None)
    except (FileNotFoundError, OSError) as exc:
        print(f"ERROR: unable to write ledger: {exc}", file=sys.stderr)
        return 2
    if args.output is None:
        sys.stdout.write(text)
    orphan_active = ledger["counts"]["orphan_active"]
    if args.fail_on_orphan_active and orphan_active:
        print(f"FAIL: {orphan_active} orphan_active workflow identit(y/ies)", file=sys.stderr)
        return 1
    print(
        f"PASS: inventoried {len(ledger['records'])} identities "
        f"({orphan_active} orphan_active)",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through main()
    raise SystemExit(main())
