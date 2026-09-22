#!/usr/bin/env python3
"""Bind release dependency-review evidence to an exact pull-request revision.

The GitHub dependency-graph compare response contains one row per changed
dependency, including direct/transitive relationship, manifest, license, and
known vulnerabilities.  This verifier rejects incomplete rows and forbidden
GNU-family licenses before emitting a deterministic machine-readable receipt.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Sequence

from packaging.licenses import InvalidLicenseExpression, canonicalize_license_expression


FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
FORBIDDEN_LICENSE_RE = re.compile(
    r"(?:^|[^A-Z])(?:A?GPL|LGPL)(?:[-+.0-9]|$)", re.IGNORECASE
)
UNVERIFIABLE_LICENSE_RE = re.compile(r"(?:^|[^A-Za-z])LicenseRef-", re.IGNORECASE)


class EvidenceError(ValueError):
    """Raised when release dependency evidence is absent or incomplete."""


def _required_text(row: dict[str, Any], key: str, index: int) -> str:
    """Return a non-empty string field or fail with its row location."""
    value = row.get(key)
    if not isinstance(value, str) or not value.strip():
        raise EvidenceError(f"dependency[{index}].{key} is required")
    return value.strip()


def dependency_rows(payload: Any) -> list[dict[str, Any]]:
    """Extract the compare API's dependency rows without accepting ambiguity."""
    rows = payload.get("dependencies") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise EvidenceError("dependency evidence must be a JSON array or dependencies array")
    if any(not isinstance(row, dict) for row in rows):
        raise EvidenceError("every dependency evidence row must be an object")
    return rows


def validate_license_expression(value: str, *, dependency_name: str) -> str:
    """Return canonical SPDX or fail closed on unknown/custom license evidence."""
    if UNVERIFIABLE_LICENSE_RE.search(value):
        raise EvidenceError(
            f"unverifiable release dependency license: {dependency_name}: {value}"
        )
    try:
        canonical = canonicalize_license_expression(value)
    except InvalidLicenseExpression as error:
        raise EvidenceError(
            f"invalid or unknown release dependency license: {dependency_name}: {value}"
        ) from error
    if UNVERIFIABLE_LICENSE_RE.search(canonical):
        raise EvidenceError(
            f"unverifiable release dependency license: {dependency_name}: {value}"
        )
    return canonical


def build_receipt(
    payload: Any, *, repository: str, base_sha: str, head_sha: str
) -> dict[str, Any]:
    """Validate every dependency and build an exact-head evidence receipt."""
    if repository.count("/") != 1:
        raise EvidenceError("repository must be owner/name")
    if not FULL_SHA_RE.fullmatch(base_sha) or not FULL_SHA_RE.fullmatch(head_sha):
        raise EvidenceError("base_sha and head_sha must be full lowercase commit SHAs")
    if base_sha == head_sha:
        raise EvidenceError("base_sha and head_sha must differ")

    dependencies: list[dict[str, Any]] = []
    for index, row in enumerate(dependency_rows(payload)):
        name = _required_text(row, "name", index)
        manifest = _required_text(row, "manifest", index)
        license_expression = validate_license_expression(
            _required_text(row, "license", index), dependency_name=name
        )
        if FORBIDDEN_LICENSE_RE.search(license_expression):
            raise EvidenceError(
                f"forbidden release dependency license: {name}: {license_expression}"
            )
        vulnerabilities = row.get("vulnerabilities")
        if not isinstance(vulnerabilities, list):
            raise EvidenceError(f"dependency[{index}].vulnerabilities must be an array")
        dependencies.append(
            {
                "name": name,
                "version": str(row.get("version") or ""),
                "manifest": manifest,
                # GitHub's compare API returns direct and transitive changes but
                # does not expose that relationship in its response schema.
                "relationship": str(row.get("relationship") or "not_reported_by_compare_api"),
                "license": license_expression,
                "change_type": str(row.get("change_type") or "unknown"),
                "vulnerabilities": vulnerabilities,
            }
        )

    dependencies.sort(
        key=lambda item: (item["manifest"], item["name"].lower(), item["version"])
    )
    return {
        "schema": "cwl-release-dependency-evidence/v1",
        "binding": {
            "repository": repository,
            "base_sha": base_sha,
            "head_sha": head_sha,
        },
        "policy": {
            "coverage": "all direct and transitive changes returned by GitHub dependency review",
            "denied_license_families": ["GPL", "LGPL", "AGPL"],
        },
        "dependency_count": len(dependencies),
        "dependencies": dependencies,
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse the exact-head evidence verifier CLI."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--head-sha", required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Validate compare evidence and atomically publish its structured receipt."""
    args = parse_args(argv)
    try:
        if not args.input.is_file() or args.input.is_symlink():
            raise EvidenceError("dependency evidence input is missing or unsafe")
        payload = json.loads(args.input.read_text(encoding="utf-8"))
        receipt = build_receipt(
            payload,
            repository=args.repository,
            base_sha=args.base_sha,
            head_sha=args.head_sha,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.output.with_suffix(args.output.suffix + ".tmp")
        temporary.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        temporary.replace(args.output)
    except (EvidenceError, OSError, json.JSONDecodeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
