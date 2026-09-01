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
    if len(set(type_map.values())) != len(type_map):
        raise TaxonomyError("managed labels must be unique")

    raw_assignments = root["assignments"]
    if type(raw_assignments) is not list:
        raise TaxonomyError("assignments must be an array")
    assignments: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
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
        key = (repository, issue)
        if key in seen:
            raise TaxonomyError("assignments contain duplicate repository/issue targets")
        seen.add(key)
        assignments.append(
            {"repository": repository, "issue": issue, "type": semantic_type}
        )
    return type_map, assignments


def _gh_api(method: str, endpoint: str, *, body: Any = None) -> str:
    """Call GitHub CLI with a bounded endpoint and optional JSON body."""

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
        raise RuntimeError(f"GitHub API request failed for {endpoint}")
    return completed.stdout


def _label_names(payload: dict[str, Any]) -> list[str]:
    """Extract a stable label-name list from an issue or pull-request payload."""

    raw_labels = payload.get("labels", [])
    if type(raw_labels) is not list:
        raise RuntimeError("GitHub issue labels payload is malformed")
    names: list[str] = []
    for raw in raw_labels:
        if type(raw) is str:
            name = raw
        elif type(raw) is dict and type(raw.get("name")) is str:
            name = raw["name"]
        else:
            raise RuntimeError("GitHub issue label entry is malformed")
        if name not in names:
            names.append(name)
    return names


def reconcile_assignment(
    assignment: dict[str, Any], type_map: dict[str, str]
) -> None:
    """Reconcile one issue or pull request while preserving unrelated labels."""

    repository = assignment["repository"]
    issue = assignment["issue"]
    desired_label = type_map[assignment["type"]]
    managed = set(type_map.values())
    endpoint = f"repos/{ORGANIZATION}/{repository}/issues/{issue}"
    payload = _plain_dict(json.loads(_gh_api("GET", endpoint)), field="GitHub issue")
    current = _label_names(payload)
    desired = [label for label in current if label not in managed]
    desired.append(desired_label)
    if current != desired:
        _gh_api("PATCH", endpoint, body={"labels": desired})


def parse_args() -> argparse.Namespace:
    """Parse validation and narrow repository selection arguments."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--taxonomy", type=Path, required=True)
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--repository", action="append", default=[])
    return parser.parse_args()


def main() -> int:
    """Validate taxonomy and reconcile every independent assignment possible."""

    args = parse_args()
    type_map, assignments = load_taxonomy(args.taxonomy)
    if args.validate_only:
        return 0
    if not os.environ.get("GH_TOKEN"):
        raise RuntimeError("GH_TOKEN is required in apply mode")

    declared_repositories = {item["repository"] for item in assignments}
    unknown = sorted(set(args.repository) - declared_repositories)
    if unknown:
        raise TaxonomyError(f"undeclared repositories requested: {', '.join(unknown)}")
    selected = set(args.repository)
    failures: list[str] = []
    for assignment in assignments:
        if selected and assignment["repository"] not in selected:
            continue
        try:
            reconcile_assignment(assignment, type_map)
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
