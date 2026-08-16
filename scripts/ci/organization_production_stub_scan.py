#!/usr/bin/env python3
"""Inventory high-confidence production stubs across supported source languages."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from collections.abc import Iterable
from dataclasses import asdict
from pathlib import Path

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


def has_excluded_runtime_part(path: Path) -> bool:
    """Return whether a path belongs to test, generated, vendored, or demo content."""
    return any(part.lower() in RUNTIME_EXCLUDED_PARTS for part in path.parts)


def is_runtime_source_path(path: Path) -> bool:
    """Return whether a path is supported production source code."""
    return path.suffix.lower() in RUNTIME_SOURCE_SUFFIXES and not has_excluded_runtime_part(path)


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
                    r"\s*\(\s*['\"](?:TODO|not implemented|unimplemented)",
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
        source_path = repo_root / relative_path
        if source_path.is_symlink():
            errors.append(f"{key} is a symbolic link and cannot be scanned")
            continue
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
    findings: list[Finding], errors: list[str], checked_count: int
) -> str:
    """Render a deterministic machine-readable inventory report."""
    ordered_findings = sorted(
        findings, key=lambda item: (item.path, item.line, item.reason)
    )
    payload = {
        "schema": "cwl.implementation-completeness/v2",
        "result": "fail" if ordered_findings or errors else "pass",
        "checked_runtime_source_files": checked_count,
        "findings": [asdict(item) for item in ordered_findings],
        "errors": sorted(errors),
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
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    if args.all_tracked:
        runtime_paths = tracked_runtime_paths(repo_root)
    else:
        changed_paths = changed_paths_from_file(Path(args.changed_files))
        runtime_paths = [
            path
            for path in dict.fromkeys(changed_paths)
            if is_runtime_source_path(path) and (repo_root / path).is_file()
        ]
    findings, errors = scan_changed_paths(repo_root, runtime_paths)
    renderer = render_json_report if args.format == "json" else render_report
    print(renderer(findings, errors, len(runtime_paths)), end="")
    return 1 if findings or errors else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
