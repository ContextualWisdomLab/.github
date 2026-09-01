"""Reconcile evidence-backed GitHub labels from a reviewed organization taxonomy."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote


ORGANIZATION = "ContextualWisdomLab"
REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


class TaxonomyError(ValueError):
    """Raised when the reviewed label taxonomy is malformed or ambiguous."""


def _plain_dict(value: Any, *, field: str) -> dict[str, Any]:
    """Return an exact dictionary or reject behavior-bearing mapping objects."""

    if type(value) is not dict:
        raise TaxonomyError(f"{field} must be an object")
    return value


def load_taxonomy(path: Path) -> tuple[dict[str, str], list[dict[str, Any]]]:
    """Load and validate semantic label mappings and explicit assignments."""

    root = _plain_dict(json.loads(path.read_text(encoding="utf-8")), field="taxonomy")
    if set(root) != {"schema_version", "type", "assignments"}:
        raise TaxonomyError("taxonomy has an unexpected key set")
    if type(root["schema_version"]) is not int or root["schema_version"] != 1:
        raise TaxonomyError("taxonomy schema is unsupported")
    raw_types = _plain_dict(root["type"], field="type")
    if not raw_types:
        raise TaxonomyError("type mappings must not be empty")
    type_map: dict[str, str] = {}
    for semantic_type, label in raw_types.items():
        if (
            type(semantic_type) is not str
            or not semantic_type
            or type(label) is not str
            or not label
        ):
            raise TaxonomyError("type mappings must use non-empty strings")
        type_map[semantic_type] = label
    if len({label.casefold() for label in type_map.values()}) != len(type_map):
        raise TaxonomyError("managed labels must be unique ignoring case")

    raw_assignments = root["assignments"]
    if type(raw_assignments) is not list:
        raise TaxonomyError("assignments must be an array")
    assignments: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    casing_by_identity: dict[str, str] = {}
    for index, raw in enumerate(raw_assignments):
        assignment = _plain_dict(raw, field=f"assignments[{index}]")
        if set(assignment) != {"repository", "issue", "type"}:
            raise TaxonomyError(f"assignments[{index}] has an unexpected key set")
        repository = assignment["repository"]
        issue = assignment["issue"]
        semantic_type = assignment["type"]
        if type(repository) is not str or not REPOSITORY_RE.fullmatch(repository):
            raise TaxonomyError(f"assignments[{index}].repository is invalid")
        if type(issue) is not int or issue < 1:
            raise TaxonomyError(f"assignments[{index}].issue is invalid")
        if semantic_type not in type_map:
            raise TaxonomyError(f"assignments[{index}].type is unknown")
        identity = repository.casefold()
        prior = casing_by_identity.get(identity)
        if prior is not None and prior != repository:
            raise TaxonomyError(
                f"repository casing collision: {prior} and {repository} identify the same GitHub repository"
            )
        casing_by_identity[identity] = repository
        key = (identity, issue)
        if key in seen:
            raise TaxonomyError("assignments contain duplicate repository/issue targets")
        seen.add(key)
        assignments.append(
            {"repository": repository, "issue": issue, "type": semantic_type}
        )
    return type_map, assignments


def _gh_api(
    method: str,
    endpoint: str,
    *,
    body: Any = None,
    allow_not_found: bool = False,
) -> str:
    """Call GitHub CLI with bounded JSON and optional idempotent 404 handling."""

    command = ["gh", "api", "--method", method, endpoint]
    if body is not None:
        command.extend(["--input", "-"])
    completed = subprocess.run(
        command,
        check=False,
        input=None if body is None else json.dumps(body, separators=(",", ":")),
        capture_output=True,
        text=True,
        timeout=30,
    )
    if completed.returncode != 0:
        combined = f"{completed.stdout}\n{completed.stderr}"
        if allow_not_found and ("HTTP 404" in combined or "Not Found" in combined):
            return ""
        raise RuntimeError(f"GitHub API request failed for {endpoint}")
    return completed.stdout


def _label_names(payload: dict[str, Any]) -> list[str]:
    """Extract a stable label-name list from an issue or pull-request payload."""

    raw_labels = payload.get("labels", [])
    if type(raw_labels) is not list:
        raise RuntimeError("GitHub issue labels payload is malformed")
    names: list[str] = []
    seen: set[str] = set()
    for raw in raw_labels:
        if type(raw) is str:
            name = raw
        elif type(raw) is dict and type(raw.get("name")) is str:
            name = raw["name"]
        else:
            raise RuntimeError("GitHub issue label entry is malformed")
        identity = name.casefold()
        if identity not in seen:
            seen.add(identity)
            names.append(name)
    return names


def _managed_labels(
    assignment: dict[str, Any], type_map: dict[str, str]
) -> tuple[str, set[str], str]:
    """Return issue endpoint, managed casefold identities, and desired label."""

    repository = assignment["repository"]
    issue = assignment["issue"]
    desired_label = type_map[assignment["type"]]
    endpoint = f"repos/{ORGANIZATION}/{repository}/issues/{issue}"
    return endpoint, {label.casefold() for label in type_map.values()}, desired_label


def reconcile_assignment(
    assignment: dict[str, Any], type_map: dict[str, str]
) -> None:
    """Mutate only taxonomy labels and preserve concurrent unrelated labels."""

    endpoint, managed, desired_label = _managed_labels(assignment, type_map)
    payload = _plain_dict(json.loads(_gh_api("GET", endpoint)), field="GitHub issue")
    current = _label_names(payload)
    desired_identity = desired_label.casefold()
    obsolete = [
        label
        for label in current
        if label.casefold() in managed and label.casefold() != desired_identity
    ]
    missing_desired = desired_identity not in {label.casefold() for label in current}
    if not obsolete and not missing_desired:
        return

    if missing_desired:
        _gh_api("POST", f"{endpoint}/labels", body={"labels": [desired_label]})
    for label in obsolete:
        encoded_label = quote(label, safe="")
        _gh_api(
            "DELETE",
            f"{endpoint}/labels/{encoded_label}",
            allow_not_found=True,
        )

    verify_assignment(assignment, type_map)


def verify_assignment(assignment: dict[str, Any], type_map: dict[str, str]) -> None:
    """Re-read one target and fail unless its managed labels exactly converge."""

    endpoint, managed, desired_label = _managed_labels(assignment, type_map)
    payload = _plain_dict(json.loads(_gh_api("GET", endpoint)), field="GitHub issue")
    current = _label_names(payload)
    managed_after = {label.casefold() for label in current if label.casefold() in managed}
    if managed_after != {desired_label.casefold()}:
        repository = assignment["repository"]
        issue = assignment["issue"]
        raise RuntimeError(
            f"managed labels did not converge for {repository}#{issue}"
        )


def parse_args() -> argparse.Namespace:
    """Parse validation, verification, and narrow repository selection arguments."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--taxonomy", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--validate-only", action="store_true")
    mode.add_argument("--verify-only", action="store_true")
    parser.add_argument("--repository", action="append", default=[])
    return parser.parse_args()


def _select_repository_identities(
    requested: list[str], assignments: list[dict[str, Any]]
) -> set[str]:
    """Canonicalize filters by case-insensitive GitHub repository identity."""

    if not requested:
        return set()
    canonical_by_identity = {
        assignment["repository"].casefold(): assignment["repository"]
        for assignment in assignments
    }
    selected: set[str] = set()
    unknown: list[str] = []
    for candidate in requested:
        identity = candidate.casefold()
        if identity not in canonical_by_identity:
            unknown.append(candidate)
        else:
            selected.add(identity)
    if unknown:
        raise TaxonomyError(f"undeclared repositories requested: {', '.join(sorted(unknown))}")
    return selected


def main() -> int:
    """Validate, reconcile, or verify every independent assignment possible."""

    args = parse_args()
    type_map, assignments = load_taxonomy(args.taxonomy)
    if args.validate_only:
        return 0
    if not os.environ.get("GH_TOKEN"):
        raise RuntimeError("GH_TOKEN is required outside validation mode")

    selected = _select_repository_identities(args.repository, assignments)
    operation = verify_assignment if getattr(args, "verify_only", False) else reconcile_assignment
    failures: list[str] = []
    for assignment in assignments:
        if selected and assignment["repository"].casefold() not in selected:
            continue
        try:
            operation(assignment, type_map)
        except (
            TaxonomyError,
            RuntimeError,
            json.JSONDecodeError,
            subprocess.TimeoutExpired,
        ) as exc:
            target = f'{assignment["repository"]}#{assignment["issue"]}'
            failures.append(f"{target}: {exc}")
            print(f"label reconciliation failed for {target}: {exc}", file=sys.stderr)
    if failures:
        raise RuntimeError("label reconciliation failed: " + "; ".join(failures))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
