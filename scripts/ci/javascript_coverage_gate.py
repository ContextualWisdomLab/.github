#!/usr/bin/env python3
"""Require full Istanbul coverage for changed JavaScript/TypeScript runtime code."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any, Sequence


METRICS = ("statements", "branches", "functions", "lines")
SOURCE_SUFFIXES = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}
EXCLUDED_PARTS = {
    "__tests__",
    "coverage",
    "dist",
    "fixtures",
    "node_modules",
    "test",
    "tests",
}
TEST_NAME_RE = re.compile(r"\.(?:spec|test)\.[cm]?[jt]sx?$")
HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def git_command(repo_root: Path, *args: str) -> list[str]:
    """Build a read-only Git command for the validated coverage worktree.

    The coverage sandbox deliberately keeps ``.git`` owned by root while tests
    run as an unprivileged UID. Git therefore requires an explicit
    ``safe.directory`` for trusted coverage code even though the worktree
    itself belongs to the test UID.
    """
    resolved_root = repo_root.resolve()
    return [
        "git",
        "-c",
        f"safe.directory={resolved_root}",
        "-C",
        str(resolved_root),
        *args,
    ]


def git(repo_root: Path, *args: str) -> str:
    """Run a read-only git command and return decoded stdout."""
    completed = subprocess.run(
        git_command(repo_root, *args),
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(detail or f"git {' '.join(args)} failed")
    return completed.stdout.decode("utf-8", errors="surrogateescape")


def is_runtime_source(path: str) -> bool:
    """Return whether a changed path is instrumentable runtime JS/TS source."""
    normalized = PurePosixPath(path)
    lowered_parts = {part.casefold() for part in normalized.parts}
    name = normalized.name.casefold()
    if normalized.suffix.casefold() not in SOURCE_SUFFIXES:
        return False
    if name.endswith(".d.ts") or TEST_NAME_RE.search(name):
        return False
    if lowered_parts & EXCLUDED_PARTS:
        return False
    if name in {
        "eslint.config.js",
        "next.config.js",
        "next.config.mjs",
        "vite.config.js",
        "vite.config.ts",
        "vitest.config.js",
        "vitest.config.ts",
    }:
        return False
    return True


def changed_runtime_lines(
    repo_root: Path, base_sha: str, head_sha: str
) -> dict[str, set[int]]:
    """Return added/modified line numbers for changed runtime source files."""
    raw_names = subprocess.run(
        git_command(
            repo_root,
            "diff",
            "--name-only",
            "-z",
            "--diff-filter=ACMR",
            base_sha,
            head_sha,
        ),
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if raw_names.returncode != 0:
        detail = raw_names.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(detail or "could not enumerate changed files")

    changed: dict[str, set[int]] = {}
    for raw_path in raw_names.stdout.split(b"\0"):
        if not raw_path:
            continue
        path = raw_path.decode("utf-8", errors="surrogateescape")
        if not is_runtime_source(path):
            continue
        diff_text = git(
            repo_root,
            "diff",
            "--unified=0",
            "--no-color",
            base_sha,
            head_sha,
            "--",
            path,
        )
        lines: set[int] = set()
        for diff_line in diff_text.splitlines():
            match = HUNK_RE.match(diff_line)
            if not match:
                continue
            start = int(match.group(1))
            count = int(match.group(2) or "1")
            lines.update(range(start, start + count))
        if lines:
            changed[path] = lines
    return changed


def percentage(covered: int, total: int) -> float:
    """Return a stable percentage for human-readable evidence."""
    return 100.0 if total == 0 else round((covered / total) * 100, 2)


def summarize_final(data: dict[str, Any]) -> dict[str, float]:
    """Compute global Istanbul metrics from coverage-final data."""
    totals = {metric: [0, 0] for metric in METRICS}
    for file_data in data.values():
        statements = file_data.get("s") or {}
        totals["statements"][1] += len(statements)
        totals["statements"][0] += sum(
            1 for count in statements.values() if count > 0
        )

        functions = file_data.get("f") or {}
        totals["functions"][1] += len(functions)
        totals["functions"][0] += sum(
            1 for count in functions.values() if count > 0
        )

        branches = file_data.get("b") or {}
        for counts in branches.values():
            totals["branches"][1] += len(counts)
            totals["branches"][0] += sum(1 for count in counts if count > 0)

        line_counts: dict[int, int] = {}
        for statement_id, location in (file_data.get("statementMap") or {}).items():
            start = (location.get("start") or {}).get("line")
            if isinstance(start, int):
                line_counts[start] = max(
                    line_counts.get(start, 0), int(statements.get(statement_id, 0))
                )
        totals["lines"][1] += len(line_counts)
        totals["lines"][0] += sum(1 for count in line_counts.values() if count > 0)

    return {
        metric: percentage(values[0], values[1])
        for metric, values in totals.items()
    }


def location_range(location: dict[str, Any] | None) -> tuple[int, int] | None:
    """Return the inclusive line range for one Istanbul location."""
    if not isinstance(location, dict):
        return None
    start = (location.get("start") or {}).get("line")
    end = (location.get("end") or {}).get("line")
    if not isinstance(start, int):
        return None
    return start, end if isinstance(end, int) else start


def intersects(location: dict[str, Any] | None, changed_lines: set[int]) -> bool:
    """Return whether an Istanbul location intersects changed lines."""
    line_range = location_range(location)
    if line_range is None:
        return False
    start, end = line_range
    return any(start <= line <= end for line in changed_lines)


def changed_metric_counts(
    records: Sequence[dict[str, Any]], changed_lines: set[int]
) -> dict[str, tuple[int, int]]:
    """Return covered/total counts for changed Istanbul execution units."""
    units: dict[str, dict[tuple[Any, ...], int]] = {
        metric: {} for metric in METRICS
    }
    for file_data in records:
        statements = file_data.get("s") or {}
        statement_map = file_data.get("statementMap") or {}
        for statement_id, location in statement_map.items():
            line_range = location_range(location)
            if line_range is None:
                continue
            if not any(
                line_range[0] <= line <= line_range[1] for line in changed_lines
            ):
                continue
            count = int(statements.get(statement_id, 0))
            units["statements"][line_range] = max(
                units["statements"].get(line_range, 0), count
            )
            start_line = line_range[0]
            units["lines"][(start_line,)] = max(
                units["lines"].get((start_line,), 0), count
            )

        functions = file_data.get("f") or {}
        for function_id, function_data in (file_data.get("fnMap") or {}).items():
            location = function_data.get("loc") or function_data.get("decl")
            line_range = location_range(location)
            if line_range is None:
                continue
            if not any(
                line_range[0] <= line <= line_range[1] for line in changed_lines
            ):
                continue
            key = (*line_range, str(function_data.get("name") or ""))
            units["functions"][key] = max(
                units["functions"].get(key, 0), int(functions.get(function_id, 0))
            )

        branches = file_data.get("b") or {}
        for branch_id, branch_data in (file_data.get("branchMap") or {}).items():
            counts = branches.get(branch_id) or []
            locations = branch_data.get("locations") or []
            for index, count in enumerate(counts):
                location = locations[index] if index < len(locations) else branch_data.get("loc")
                line_range = location_range(location)
                if line_range is None:
                    continue
                if not any(
                    line_range[0] <= line <= line_range[1]
                    for line in changed_lines
                ):
                    continue
                key = (*line_range, str(branch_data.get("type") or ""), index)
                units["branches"][key] = max(
                    units["branches"].get(key, 0), int(count)
                )

    return {
        metric: (sum(1 for count in values.values() if count > 0), len(values))
        for metric, values in units.items()
    }


def normalize_coverage_path(
    raw_path: str, repo_root: Path, changed_paths: set[str]
) -> str | None:
    """Match an Istanbul path to one changed repository-relative path."""
    candidate = Path(raw_path)
    if candidate.is_absolute():
        try:
            relative = candidate.resolve(strict=False).relative_to(repo_root)
            normalized = relative.as_posix()
            if normalized in changed_paths:
                return normalized
        except ValueError:
            pass
    else:
        normalized = PurePosixPath(raw_path.lstrip("./")).as_posix()
        if normalized in changed_paths:
            return normalized

    slash_path = raw_path.replace("\\", "/").rstrip("/")
    suffix_matches = [
        path for path in changed_paths if slash_path.endswith(f"/{path}")
    ]
    return suffix_matches[0] if len(suffix_matches) == 1 else None


def likely_runtime_lines(repo_root: Path, path: str, changed_lines: set[int]) -> list[int]:
    """Return changed lines that look executable when Istanbul maps no units."""
    source_lines = (repo_root / path).read_text(
        encoding="utf-8", errors="replace"
    ).splitlines()
    runtime_lines: list[int] = []
    in_block_comment = False
    for line_number, raw_line in enumerate(source_lines, start=1):
        stripped = raw_line.strip()
        if stripped.startswith("/*"):
            in_block_comment = True
        non_runtime = (
            not stripped
            or in_block_comment
            or stripped.startswith("//")
            or stripped in {"{", "}", "};", ");", "]", "],"}
            or stripped.startswith(("interface ", "type ", "export type ", "import type "))
        )
        if line_number in changed_lines and not non_runtime:
            runtime_lines.append(line_number)
        if "*/" in stripped:
            in_block_comment = False
    return runtime_lines


def load_coverage_files(
    repo_root: Path, summary_list: Path
) -> tuple[list[tuple[Path, dict[str, Any]]], list[tuple[Path, dict[str, Any]]]]:
    """Load summary and final Istanbul files listed by the workflow."""
    summaries: list[tuple[Path, dict[str, Any]]] = []
    finals: list[tuple[Path, dict[str, Any]]] = []
    for raw_path in summary_list.read_text(encoding="utf-8").splitlines():
        if not raw_path.strip():
            continue
        path = Path(raw_path.strip())
        if not path.is_absolute():
            path = repo_root / path
        data = json.loads(path.read_text(encoding="utf-8"))
        if path.name == "coverage-final.json":
            finals.append((path, data))
        elif path.name == "coverage-summary.json":
            summaries.append((path, data))
    return summaries, finals


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--summary-list", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Print coverage evidence and fail only for incomplete changed-code coverage."""
    args = parse_args(argv)
    repo_root = args.repo_root.resolve()
    print("# JavaScript/TypeScript Coverage Evidence")
    try:
        summaries, finals = load_coverage_files(repo_root, args.summary_list)
        changed = changed_runtime_lines(repo_root, args.base_sha, args.head_sha)
    except (OSError, RuntimeError, json.JSONDecodeError) as exc:
        print("\n- Result: FAIL")
        print(f"- Reason: coverage evidence could not be evaluated: {exc}")
        return 1

    print("\n## Global coverage advisory")
    for path, data in summaries:
        metrics = {
            metric: (data.get("total") or {}).get(metric, {}).get("pct")
            for metric in METRICS
        }
        print(f"- {path.relative_to(repo_root)}")
        for metric in METRICS:
            print(f"  {metric}: {metrics.get(metric)}%")
    for path, data in finals:
        metrics = summarize_final(data)
        print(f"- {path.relative_to(repo_root)} (derived)")
        for metric in METRICS:
            print(f"  {metric}: {metrics[metric]}%")
    print("- Decision: advisory only; pre-existing global debt is visible but does not mask changed-code evidence.")

    if not changed:
        print("\n## Changed-source coverage")
        print("- No changed JavaScript/TypeScript runtime source files; coverage is not applicable.")
        print("- Result: PASS")
        return 0
    if not finals:
        print("\n## Changed-source coverage")
        print("- Result: FAIL")
        print("- Reason: coverage-final.json is required for changed-line evidence but was not produced.")
        return 1

    changed_paths = set(changed)
    records: dict[str, list[dict[str, Any]]] = {path: [] for path in changed}
    for _coverage_path, final_data in finals:
        for raw_path, file_data in final_data.items():
            matched = normalize_coverage_path(raw_path, repo_root, changed_paths)
            if matched is not None:
                records[matched].append(file_data)

    failures: list[str] = []
    print("\n## Changed-source coverage")
    for path, changed_lines in sorted(changed.items()):
        if not records[path]:
            print(f"- {path}: missing instrumentation")
            failures.append(f"{path} is absent from coverage-final.json")
            continue
        counts = changed_metric_counts(records[path], changed_lines)
        metric_text = ", ".join(
            f"{metric} {covered}/{total}"
            for metric, (covered, total) in counts.items()
        )
        print(f"- {path}: {metric_text}")
        total_units = sum(total for _covered, total in counts.values())
        if total_units == 0:
            runtime_lines = likely_runtime_lines(repo_root, path, changed_lines)
            if runtime_lines:
                failures.append(
                    f"{path} changed runtime-looking lines {runtime_lines} but Istanbul mapped no execution units"
                )
            else:
                print("  changed lines are comments, delimiters, or type-only declarations; no executable units apply")
            continue
        for metric, (covered, total) in counts.items():
            if total and covered != total:
                failures.append(
                    f"{path} changed {metric} coverage is {covered}/{total}"
                )

    if failures:
        print("\n- Result: FAIL")
        print("- Reasons:")
        for failure in failures:
            print(f"  - {failure}")
        return 1

    print("\n- Result: PASS")
    print("- Reason: every instrumented execution unit intersecting changed runtime lines is covered.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
