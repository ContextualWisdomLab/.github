#!/usr/bin/env python3
"""Fail closed when production consumers bypass adaptive orchestration."""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


SOURCE_SUFFIXES = frozenset(
    {".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".rs", ".go", ".java", ".kt", ".cs"}
)
EXCLUDED_PARTS = frozenset(
    {
        ".git",
        ".github",
        "build",
        "dist",
        "docs",
        "examples",
        "fixtures",
        "migrations",
        "node_modules",
        "scripts",
        "spec",
        "specs",
        "target",
        "test",
        "tests",
        "vendor",
    }
)
ORCHESTRATOR_MARKERS = ("contextual-orchestrator", "contextual_orchestrator")
CHAT_ENDPOINT_MARKERS = ("/v1/chat/completions", "/chat/completions", "chat/completions")
FORCED_ROUTE_PATTERN = re.compile(
    r"(?:orchestration_mode|mode)(?:\s*:\s*str)?\s*[:=]\s*[\"']?\broute\b[\"']?",
    re.IGNORECASE,
)
AUTO_PATTERN = re.compile(
    r"(?:orchestration_mode|mode)(?:\s*:\s*str)?\s*[:=]\s*[\"']?\bauto\b[\"']?",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Finding:
    """One source-backed adaptive-orchestration policy violation."""

    finding_code: str
    source_path: str
    message: str

    def as_dict(self) -> dict[str, str]:
        """Return the stable JSON representation used by workflow evidence."""

        return {
            "finding_code": self.finding_code,
            "source_path": self.source_path,
            "message": self.message,
        }


def _load_policy(root: Path) -> dict[str, list[str]]:
    """Load narrowly scoped path exceptions, failing closed when malformed."""

    path = root / ".cwl" / "contextual_orchestrator_policy.json"
    if not path.exists():
        return {"allowed_fixed_mode_paths": [], "request_constructor_exemptions": []}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("contextual_orchestrator_policy.json must contain an object")
    policy: dict[str, list[str]] = {}
    for key in ("allowed_fixed_mode_paths", "request_constructor_exemptions"):
        entries = value.get(key, [])
        if not isinstance(entries, list) or any(not isinstance(item, str) for item in entries):
            raise ValueError(f"{key} must be an array of path globs")
        policy[key] = entries
    return policy


def _matches(path: str, patterns: Iterable[str]) -> bool:
    """Return whether a relative source path matches an exception glob."""

    return any(fnmatch.fnmatch(path, pattern) for pattern in patterns)


def _production_sources(root: Path) -> Iterable[Path]:
    """Yield supported source files outside non-production path components."""

    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in SOURCE_SUFFIXES:
            continue
        relative = path.relative_to(root)
        if {part.lower() for part in relative.parts} & EXCLUDED_PARTS:
            continue
        yield path


def inspect_repository(root: Path) -> list[Finding]:
    """Return every forced-route or implicit-mode production violation."""

    policy = _load_policy(root)
    findings: list[Finding] = []
    for path in _production_sources(root):
        relative = path.relative_to(root).as_posix()
        text = path.read_text(encoding="utf-8", errors="strict")
        lowered = text.lower()
        if not any(marker in lowered for marker in ORCHESTRATOR_MARKERS):
            continue
        fixed_allowed = _matches(relative, policy["allowed_fixed_mode_paths"])
        constructor_exempt = _matches(relative, policy["request_constructor_exemptions"])
        if FORCED_ROUTE_PATTERN.search(text) and not fixed_allowed:
            findings.append(
                Finding(
                    "forced_single_route",
                    relative,
                    "production contextual-orchestrator code forces route instead of delegating to auto",
                )
            )
        has_chat_request = any(marker in lowered for marker in CHAT_ENDPOINT_MARKERS)
        names_gateway_model = "contextual-orchestrator" in lowered
        if (
            has_chat_request
            and names_gateway_model
            and not AUTO_PATTERN.search(text)
            and not constructor_exempt
            and not fixed_allowed
        ):
            findings.append(
                Finding(
                    "implicit_orchestration_mode",
                    relative,
                    "production chat request must explicitly select contextual-orchestrator auto",
                )
            )
    return findings


def _write_json_output(path_value: str, rendered: str) -> None:
    """Write evidence through a real parent and a no-follow output binding."""

    requested = Path(path_value)
    parent = requested.parent.resolve(strict=True)
    target = parent / requested.name
    if target.exists() and target.is_symlink():
        raise ValueError("json output must not be a symbolic link")
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    no_follow = getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(target, flags | no_follow, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        output.write(rendered + "\n")


def main(argv: Sequence[str] | None = None) -> int:
    """Scan one repository, print bounded JSON, and return a policy status."""

    parser = argparse.ArgumentParser()
    parser.add_argument("repository_root", nargs="?", default=".")
    parser.add_argument("--json-output")
    args = parser.parse_args(argv)
    root = Path(args.repository_root).resolve()
    findings = inspect_repository(root)
    rendered = json.dumps(
        {
            "policy_name": "contextual_orchestrator_adaptive_default",
            "repository_root": str(root),
            "finding_count": len(findings),
            "findings": [finding.as_dict() for finding in findings],
        },
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    print(rendered)
    if args.json_output:
        _write_json_output(args.json_output, rendered)
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
