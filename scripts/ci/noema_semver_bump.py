#!/usr/bin/env python3
"""Fail-closed semantic-version gate for the central release pipeline.

Automatic decisions and model-response parsing remain unavailable until
fast-mlsirm publishes a calibrated release-decision receipt and
contextual-orchestrator publishes its immutable client/schema.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Mapping

BUMP_VALUES = frozenset({"major", "minor", "patch"})
CORE_SEMVER_RE = re.compile(
    r"^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)$"
)
class SemverBumpError(RuntimeError):
    """Fail-closed release-bump failure that must stop the cut."""


def parse_core_semver(version: str) -> tuple[int, int, int]:
    """Parse a three-component core semver string into integers."""
    text = version.strip().lstrip("v")
    if CORE_SEMVER_RE.fullmatch(text) is None:
        raise SemverBumpError(
            f"version must be canonical three-component semver, got {version!r}"
        )
    major_s, minor_s, patch_s = text.split(".")
    return int(major_s), int(minor_s), int(patch_s)


def apply_bump(previous_version: str, bump: str) -> str:
    """Apply a semver bump class to ``previous_version``."""
    if bump not in BUMP_VALUES:
        raise SemverBumpError(f"unknown bump class {bump!r}")
    major, minor, patch = parse_core_semver(previous_version)
    if bump == "major":
        return f"{major + 1}.0.0"
    if bump == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def load_evidence(path: Path) -> dict[str, Any]:
    """Load the release evidence pack JSON."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SemverBumpError(f"unable to read evidence pack: {exc}") from exc
    if not isinstance(payload, dict):
        raise SemverBumpError("evidence pack must be a JSON object")
    return payload


def detected_breaking_refs(evidence: Mapping[str, Any]) -> tuple[str, ...]:
    """Return evidence refs that independently imply a breaking change.

    Removed/renamed public symbols and unsourced-default removals that make
    arguments required (ADR-0028 style) are breaking. Deprecated-alias-only
    changes are intentionally excluded (they are minor).
    """
    refs: list[str] = []
    for key, prefix in (
        ("removed_public_symbols", "api:removed:"),
        ("renamed_public_symbols", "api:renamed:"),
        ("required_arg_promotions", "api:required-arg:"),
    ):
        values = evidence.get(key) or []
        if not isinstance(values, list):
            raise SemverBumpError(f"evidence.{key} must be a list")
        for item in values:
            if not isinstance(item, str) or not item.strip():
                raise SemverBumpError(f"evidence.{key} entries must be non-empty strings")
            refs.append(f"{prefix}{item.strip()}")
    return tuple(refs)


def decide_release_version(
    evidence: Mapping[str, Any],
    *,
    previous_version: str | None = None,
    requested_version: str | None = None,
) -> dict[str, Any]:
    """Fail closed until released calibrated owner contracts are pinned."""
    del evidence, previous_version, requested_version
    raise SemverBumpError(
        "automatic Noema SemVer decisions require a released fast-mlsirm "
        "calibrated release-decision receipt and immutable "
        "contextual-orchestrator client/schema"
    )


def build_parser() -> argparse.ArgumentParser:
    """CLI parser for the release-tag workflow step."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--evidence",
        type=Path,
        required=True,
        help="Path to the evidence pack JSON",
    )
    parser.add_argument(
        "--previous-version",
        default="",
        help="Override evidence.previous_version",
    )
    parser.add_argument(
        "--requested-version",
        default="",
        help="Optional human-requested version that must match the Noema bump",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Write provenance JSON here",
    )
    parser.add_argument(
        "--notes-prefix",
        type=Path,
        help="Optional path for the release-notes Noema quote block",
    )
    parser.add_argument(
        "--github-output",
        type=Path,
        help="Optional GitHub Actions output file to append release_version",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point used by the reusable release-tag workflow."""
    parser = build_parser()
    args = parser.parse_args(argv)
    evidence = load_evidence(args.evidence)
    try:
        decide_release_version(
            evidence,
            previous_version=args.previous_version or None,
            requested_version=args.requested_version or None,
        )
    except SemverBumpError as exc:
        print(f"::error::Noema semver gate failed: {exc}", file=sys.stderr)
        return 1

    raise AssertionError("fail-closed decision unexpectedly returned")


if __name__ == "__main__":
    raise SystemExit(main())
