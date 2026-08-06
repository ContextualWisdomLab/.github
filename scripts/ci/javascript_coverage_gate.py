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
TYPE_IDENTIFIER_PATTERN = r"[$A-Z_a-z][$\w]*"
TYPE_MODULE_LITERAL_PATTERN = (
    r"(?:'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\")"
)
INTERFACE_RE = re.compile(
    rf"^(?:export\s+)?(?:declare\s+)?interface\s+"
    rf"{TYPE_IDENTIFIER_PATTERN}\s*\{{"
)
STRING_LITERAL_RE = re.compile(
    r"'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"|`(?:\\.|[^`\\])*`"
)
TYPE_IMPORT_SINGLE_RE = re.compile(
    rf"^import\s+type\s+(?:{TYPE_IDENTIFIER_PATTERN}|\{{[^{{}}]*\}})"
    rf"\s+from\s+{TYPE_MODULE_LITERAL_PATTERN}\s*;?$"
)
TYPE_IMPORT_START_RE = re.compile(r"^import\s+type\s+\{\s*$")
TYPE_IMPORT_MEMBER_RE = re.compile(
    rf"^(?:type\s+)?{TYPE_IDENTIFIER_PATTERN}"
    rf"(?:\s+as\s+{TYPE_IDENTIFIER_PATTERN})?,?$"
)
TYPE_IMPORT_END_RE = re.compile(
    rf"^\}}\s+from\s+{TYPE_MODULE_LITERAL_PATTERN}\s*;?$"
)


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
                location = (
                    locations[index]
                    if index < len(locations)
                    else branch_data.get("loc")
                )
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


def _type_code_without_comments(line: str) -> tuple[str | None, bool]:
    """Return comment-free TypeScript code and an open-comment indicator.

    Complete quoted literals are masked before comment recognition so comment
    markers inside module specifiers or string-literal types remain ordinary
    syntax. Unmatched quotes and stray block-comment closers return ``None`` so
    the caller classifies the line as runtime-looking rather than repairing it.
    """
    masked = STRING_LITERAL_RE.sub(
        lambda match: " " * len(match.group(0)),
        line,
    )
    if any(quote in masked for quote in ("'", '"', "`")):
        return None, False

    code = list(line)
    cursor = 0
    while True:
        line_comment = masked.find("//", cursor)
        block_start = masked.find("/*", cursor)
        if line_comment >= 0 and (
            block_start < 0 or line_comment < block_start
        ):
            return "".join(code[:line_comment]).strip(), False
        if block_start < 0:
            break
        block_end = masked.find("*/", block_start + 2)
        if block_end < 0:
            for index in range(block_start, len(code)):
                code[index] = " "
            return "".join(code).strip(), True
        for index in range(block_start, block_end + 2):
            code[index] = " "
        masked = (
            masked[:block_start]
            + (" " * (block_end + 2 - block_start))
            + masked[block_end + 2 :]
        )
        cursor = block_start

    if "*/" in masked:
        return None, False
    return "".join(code).strip(), False


def _advance_interface_state(
    structural: str, depth: int
) -> tuple[int, str | None]:
    """Advance interface brace depth and return code after its closing brace.

    ``None`` means the declaration remains open. A string tail means the outer
    declaration closed on this line; only an empty tail or standalone semicolon
    can remain syntax-erased.
    """
    for index, character in enumerate(structural):
        if character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth <= 0:
                return depth, structural[index + 1 :].strip()
    return depth, None


def likely_runtime_lines(
    repo_root: Path, path: str, changed_lines: set[int]
) -> list[int]:
    """Return changed lines that look executable when Istanbul maps no units.

    Only a narrow grammar of complete ``import type`` declarations and balanced
    simple TypeScript interfaces is accepted as syntax-erased. Runtime tails,
    malformed literals or comments, unsupported declaration forms, and
    unterminated lexical or declaration state remain runtime-looking so omitted
    instrumentation fails closed.
    """
    source_lines = (repo_root / path).read_text(
        encoding="utf-8", errors="replace"
    ).splitlines()
    runtime_lines: list[int] = []
    in_block_comment = False
    block_comment_changed_lines: list[int] = []
    in_type_import = False
    type_import_changed_lines: list[int] = []
    in_interface = False
    interface_changed_lines: list[int] = []
    interface_depth = 0

    for line_number, raw_line in enumerate(source_lines, start=1):
        stripped = raw_line.strip()
        syntax_invalid = False
        comment_only = False

        if in_block_comment:
            block_end = stripped.find("*/")
            if block_end < 0:
                code = ""
                comment_only = True
            else:
                in_block_comment = False
                block_comment_changed_lines.clear()
                tail = stripped[block_end + 2 :].strip()
                if not tail or tail.startswith("//"):
                    code = ""
                    comment_only = True
                else:
                    code, in_block_comment = _type_code_without_comments(tail)
                    syntax_invalid = code is None
                    if code is None:
                        code = tail
                    comment_only = not code and not syntax_invalid
        else:
            code, in_block_comment = _type_code_without_comments(stripped)
            syntax_invalid = code is None
            if code is None:
                code = stripped
            comment_only = not code and bool(stripped) and not syntax_invalid

        if in_block_comment and line_number in changed_lines:
            block_comment_changed_lines.append(line_number)

        type_only = False
        if not comment_only and not syntax_invalid:
            if in_type_import:
                if TYPE_IMPORT_END_RE.fullmatch(code):
                    type_only = True
                    in_type_import = False
                    type_import_changed_lines.clear()
                elif TYPE_IMPORT_MEMBER_RE.fullmatch(code):
                    type_only = True
                else:
                    in_type_import = False
            elif in_interface:
                structural = STRING_LITERAL_RE.sub("", code).strip()
                interface_depth, tail = _advance_interface_state(
                    structural,
                    interface_depth,
                )
                if tail is None:
                    type_only = True
                else:
                    in_interface = False
                    interface_changed_lines.clear()
                    type_only = interface_depth == 0 and tail in {"", ";"}
            elif TYPE_IMPORT_SINGLE_RE.fullmatch(code):
                type_only = True
            elif TYPE_IMPORT_START_RE.fullmatch(code):
                type_only = True
                in_type_import = True
            elif INTERFACE_RE.match(code):
                structural = STRING_LITERAL_RE.sub("", code).strip()
                interface_depth, tail = _advance_interface_state(structural, 0)
                if tail is None:
                    in_interface = interface_depth > 0
                    type_only = in_interface
                else:
                    type_only = interface_depth == 0 and tail in {"", ";"}

        if in_type_import and line_number in changed_lines:
            type_import_changed_lines.append(line_number)
        if in_interface and line_number in changed_lines:
            interface_changed_lines.append(line_number)

        non_runtime = (
            not stripped
            or comment_only
            or stripped.startswith("//")
            or stripped in {"{", "}", "};", ");", "]", "],"}
            or type_only
        )
        if line_number in changed_lines and not non_runtime:
            runtime_lines.append(line_number)

    if in_type_import:
        runtime_lines.extend(type_import_changed_lines)
    if in_interface:
        runtime_lines.extend(interface_changed_lines)
    if in_block_comment:
        runtime_lines.extend(block_comment_changed_lines)
    return sorted(set(runtime_lines))


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
    print(
        "- Decision: advisory only; pre-existing global debt is visible but "
        "does not mask changed-code evidence."
    )

    if not changed:
        print("\n## Changed-source coverage")
        print(
            "- No changed JavaScript/TypeScript runtime source files; "
            "coverage is not applicable."
        )
        print("- Result: PASS")
        return 0
    if not finals:
        print("\n## Changed-source coverage")
        print("- Result: FAIL")
        print(
            "- Reason: coverage-final.json is required for changed-line "
            "evidence but was not produced."
        )
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
            runtime_lines = likely_runtime_lines(repo_root, path, changed_lines)
            if runtime_lines:
                print(f"- {path}: missing instrumentation")
                failures.append(f"{path} is absent from coverage-final.json")
            else:
                print(f"- {path}: no executable changed units")
                print(
                    "  changed lines are comments, delimiters, or type-only "
                    "declarations; no executable units apply"
                )
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
                    f"{path} changed runtime-looking lines {runtime_lines} "
                    "but Istanbul mapped no execution units"
                )
            else:
                print(
                    "  changed lines are comments, delimiters, or type-only "
                    "declarations; no executable units apply"
                )
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
    print(
        "- Reason: every instrumented execution unit intersecting changed "
        "runtime lines is covered."
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
