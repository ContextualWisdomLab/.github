#!/usr/bin/env python3
"""Inventory high-confidence production stubs across supported source languages."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from collections.abc import Iterable, Mapping
from dataclasses import asdict
from pathlib import Path
from typing import Any

from scripts.ci import implementation_completeness_scan as base_scan

Finding = base_scan.Finding

RUNTIME_EXCLUDED_PARTS = {
    ".git",
    "build",
    "demo",
    "demos",
    "dist",
    "doc",
    "docs",
    "example",
    "examples",
    "fixture",
    "fixtures",
    "generated",
    "node_modules",
    "target",
    "test",
    "tests",
    "testing",
    "third_party",
    "vendor",
}
RUNTIME_SOURCE_SUFFIXES = {
    ".cjs",
    ".cs",
    ".go",
    ".java",
    ".js",
    ".jsx",
    ".kt",
    ".kts",
    ".mjs",
    ".py",
    ".rs",
    ".ts",
    ".tsx",
}
SUPPRESSION_MARKER = "cwl-stub-scan: allow"
GIT_INVENTORY_TIMEOUT_SECONDS = 300
MAX_RUNTIME_FILE_BYTES = 4 * 1024 * 1024
COMMIT_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
INVENTORY_SCHEMA = "cwl.implementation-completeness/v2"


def has_excluded_runtime_part(path: Path) -> bool:
    """Return whether a path belongs to test, generated, vendored, or demo content."""
    return any(part.lower() in RUNTIME_EXCLUDED_PARTS for part in path.parts)


def is_runtime_source_path(path: Path) -> bool:
    """Return whether a path is supported production source code."""
    return path.suffix.lower() in RUNTIME_SOURCE_SUFFIXES and not has_excluded_runtime_part(path)


def require_commit_sha(value: str, flag_name: str) -> str:
    """Return a 40-character lowercase Git commit SHA or raise ValueError."""
    normalized = value.strip().lower()
    if COMMIT_SHA_PATTERN.fullmatch(normalized) is None:
        raise ValueError(f"{flag_name} must be a 40-character commit SHA")
    return normalized


def require_repository_name(value: str) -> str:
    """Return owner/name when the inventory identity has exactly two non-empty parts."""
    owner, separator, name = value.partition("/")
    if separator != "/" or not owner or not name or "/" in name:
        raise ValueError("repository must be owner/name")
    return value


def symlink_rejection_message(relative_path: Path) -> str:
    """Return the stable fail-closed message for a symbolic-link runtime path."""
    return f"{relative_path.as_posix()} is a symbolic link and cannot be scanned"


def first_symlink_on_relative_path(repo_root: Path, relative_path: Path) -> Path | None:
    """Return the first symlink from the repository root through the relative path."""
    current = repo_root
    for part in relative_path.parts:
        current = current / part
        if current.is_symlink():
            return current
    return None


def is_inventory_candidate(repo_root: Path, relative_path: Path) -> bool:
    """Return whether a changed path must be scanned or rejected fail-closed."""
    if first_symlink_on_relative_path(repo_root, relative_path) is not None:
        return True
    return (repo_root / relative_path).is_file()


def inventory_payload_is_binding(payload: object) -> bool:
    """Return whether a parsed object is a usable v2 inventory."""
    if not isinstance(payload, Mapping):
        return False
    if payload.get("schema") != INVENTORY_SCHEMA:
        return False
    if payload.get("result") not in {"pass", "fail"}:
        return False
    if not isinstance(payload.get("findings"), list):
        return False
    if not isinstance(payload.get("errors"), list):
        return False
    return isinstance(payload.get("checked_runtime_source_files"), int)


def inventory_payload_is_clean(payload: Mapping[str, Any]) -> bool:
    """Return whether a valid inventory may close a remediation issue."""
    return (
        payload.get("result") == "pass"
        and payload.get("findings") == []
        and payload.get("errors") == []
    )


def tracked_runtime_paths(repo_root: Path) -> list[Path]:
    """Return tracked production source paths using a NUL-delimited Git inventory."""
    try:
        completed = subprocess.run(
            ["git", "-C", str(repo_root), "ls-files", "-z"],
            check=True,
            capture_output=True,
            timeout=GIT_INVENTORY_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"Git inventory timed out after {GIT_INVENTORY_TIMEOUT_SECONDS} seconds"
        ) from exc
    paths = [
        Path(raw.decode("utf-8", errors="surrogateescape"))
        for raw in completed.stdout.split(b"\0")
        if raw
    ]
    return sorted(path for path in paths if is_runtime_source_path(path))


def generic_runtime_findings(relative_path: Path, source: str) -> list[Finding]:
    """Find high-confidence cross-language runtime mock and stub markers."""
    findings: list[Finding] = []
    suffix = relative_path.suffix.lower()
    explicit_patterns: tuple[tuple[re.Pattern[str], str], ...] = (
        (
            re.compile(r"(?i)\bmock implementation\b|\bin a real implementation\b"),
            "explicit runtime mock marker",
        ),
        (
            re.compile(
                r"(?i)webhook\s*\(stub\)|\bstubbed implementation\b|"
                r"\bstub implementation\b"
            ),
            "explicit runtime stub marker",
        ),
        (
            re.compile(r"['\"]demo_user['\"]"),
            "hard-coded demo principal in runtime code",
        ),
        (
            re.compile(
                r"billing=mock.*\bmock\s*:\s*true|"
                r"\bmock\s*:\s*true.*billing=mock",
                re.IGNORECASE,
            ),
            "demo-only mock success path in runtime code",
        ),
        (
            re.compile(
                r"(?:app|router)\.(?:get|post|put|patch|delete|all)"
                r"\([^\n]*['\"][^'\"]*/mock/",
                re.IGNORECASE,
            ),
            "runtime mock endpoint",
        ),
    )
    executable_patterns: list[tuple[re.Pattern[str], str]] = []
    if suffix in {".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx"}:
        executable_patterns.extend(
            [
                (
                    re.compile(
                        r"throw\s+new\s+Error\s*\(\s*['\"]"
                        r"(?:not implemented|unimplemented)(?:[^'\"]*)"
                        r"['\"]\s*\)",
                        re.IGNORECASE,
                    ),
                    "throws an explicit not-implemented error",
                ),
                (
                    re.compile(
                        r"Promise\.reject\s*\(\s*new\s+Error\s*"
                        r"\(\s*['\"]TODO(?::|\b)",
                        re.IGNORECASE,
                    ),
                    "rejects with an explicit TODO implementation error",
                ),
            ]
        )
    elif suffix == ".go":
        executable_patterns.append(
            (
                re.compile(
                    r"panic\s*\(\s*['\"](?:TODO|not implemented|unimplemented)"
                    r"(?:[^'\"]*)['\"]\s*\)",
                    re.IGNORECASE,
                ),
                "panics with an explicit not-implemented marker",
            )
        )
    elif suffix in {".java", ".kt", ".kts", ".cs"}:
        executable_patterns.append(
            (
                re.compile(
                    r"(?:UnsupportedOperationException|NotImplementedException)"
                    r"\s*\(\s*(?:['\"](?:TODO|not implemented|unimplemented)"
                    r"[^'\"]*['\"]\s*)?\)",
                    re.IGNORECASE,
                ),
                "throws an explicit not-implemented exception",
            )
        )
    for line_number, line in enumerate(source.splitlines(), start=1):
        if SUPPRESSION_MARKER in line.lower():
            continue
        for pattern, reason in (*explicit_patterns, *executable_patterns):
            if pattern.search(line):
                findings.append(
                    Finding(
                        path=relative_path.as_posix(),
                        line=line_number,
                        symbol="runtime",
                        reason=reason,
                    )
                )
    return findings


def changed_paths_from_file(path: Path) -> list[Path]:
    """Read a newline-delimited changed-file list using the central base scanner."""
    return base_scan.changed_paths_from_file(path)


def scan_changed_paths(
    repo_root: Path, changed_paths: Iterable[Path]
) -> tuple[list[Finding], list[str]]:
    """Scan selected production source paths and return findings plus parse errors."""
    findings: list[Finding] = []
    errors: list[str] = []
    seen: set[str] = set()
    for relative_path in changed_paths:
        key = relative_path.as_posix()
        if key in seen or not is_runtime_source_path(relative_path):
            continue
        seen.add(key)
        if first_symlink_on_relative_path(repo_root, relative_path) is not None:
            errors.append(symlink_rejection_message(relative_path))
            continue
        source_path = repo_root / relative_path
        if not source_path.is_file():
            continue
        if source_path.stat().st_size > MAX_RUNTIME_FILE_BYTES:
            errors.append(
                f"{key} exceeds the {MAX_RUNTIME_FILE_BYTES} byte scan limit"
            )
            continue
        source = source_path.read_text(encoding="utf-8", errors="replace")
        findings.extend(generic_runtime_findings(relative_path, source))
        suffix = relative_path.suffix.lower()
        if suffix == ".py":
            try:
                findings.extend(base_scan.scan_python_file(repo_root, relative_path))
            except SyntaxError as exc:
                line = exc.lineno or 1
                errors.append(f"{key}:{line} could not be parsed: {exc.msg}")
        elif suffix == ".rs":
            findings.extend(base_scan.scan_rust_file(repo_root, relative_path))
    findings.sort(key=lambda item: (item.path, item.line, item.reason))
    return findings, sorted(errors)


def render_report(findings: list[Finding], errors: list[str], checked_count: int) -> str:
    """Render a human-readable production-stub inventory."""
    lines = [
        "# Organization Production Stub Scan",
        "",
        f"- Checked runtime source files: {checked_count}",
        f"- Result: {'FAIL' if findings or errors else 'PASS'}",
    ]
    if errors:
        lines.extend(["", "Parse errors:"])
        lines.extend(f"- {error}" for error in errors)
    if findings:
        lines.extend(["", "Findings:"])
        lines.extend(
            f"- {item.path}:{item.line} `{item.symbol}` - {item.reason}"
            for item in findings
        )
    if not findings and not errors:
        lines.extend(["", "No executable or explicit runtime stubs were found."])
    return "\n".join(lines) + "\n"


def render_json_report(
    findings: list[Finding],
    errors: list[str],
    checked_count: int,
    *,
    repository: str | None = None,
    repository_sha: str | None = None,
    workflow_sha: str | None = None,
) -> str:
    """Render a deterministic machine-readable inventory report."""
    ordered_findings = sorted(
        findings, key=lambda item: (item.path, item.line, item.reason)
    )
    payload = {
        "schema": INVENTORY_SCHEMA,
        "result": "fail" if ordered_findings or errors else "pass",
        "checked_runtime_source_files": checked_count,
        "findings": [asdict(item) for item in ordered_findings],
        "errors": sorted(errors),
        "repository": repository,
        "repository_sha": repository_sha,
        "workflow_sha": workflow_sha,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main() -> int:
    """Run the production-stub inventory command-line interface."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    inventory = parser.add_mutually_exclusive_group(required=True)
    inventory.add_argument("--changed-files")
    inventory.add_argument("--all-tracked", action="store_true")
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument("--repository")
    parser.add_argument("--repository-sha")
    parser.add_argument("--workflow-sha")
    args = parser.parse_args()

    try:
        repository = (
            require_repository_name(args.repository) if args.repository else None
        )
        repository_sha = (
            require_commit_sha(args.repository_sha, "--repository-sha")
            if args.repository_sha
            else None
        )
        workflow_sha = (
            require_commit_sha(args.workflow_sha, "--workflow-sha")
            if args.workflow_sha
            else None
        )
    except ValueError as exc:
        parser.error(str(exc))

    repo_root = Path(args.repo_root).resolve()
    if args.all_tracked:
        runtime_paths = tracked_runtime_paths(repo_root)
    else:
        changed_paths = changed_paths_from_file(Path(args.changed_files))
        runtime_paths = [
            path
            for path in dict.fromkeys(changed_paths)
            if is_runtime_source_path(path) and is_inventory_candidate(repo_root, path)
        ]
    findings, errors = scan_changed_paths(repo_root, runtime_paths)
    if args.format == "json":
        print(
            render_json_report(
                findings,
                errors,
                len(runtime_paths),
                repository=repository,
                repository_sha=repository_sha,
                workflow_sha=workflow_sha,
            ),
            end="",
        )
    else:
        print(render_report(findings, errors, len(runtime_paths)), end="")
    return 1 if findings or errors else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
