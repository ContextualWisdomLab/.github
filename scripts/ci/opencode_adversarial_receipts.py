#!/usr/bin/env python3
"""Emit trusted current-head source-line receipts for OpenCode probes."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Sequence


GIT_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
HUNK_RE = re.compile(rb"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
MAX_SOURCE_BYTES = 2 * 1024 * 1024
MAX_CHANGED_PATHS = 200


@dataclass(frozen=True)
class SourceLineReceipt:
    """A digest bound to one exact line in a current-head changed file."""

    path: str
    line: int
    digest: str


def validate_git_sha(value: str, label: str) -> str:
    """Return a normalized Git SHA or raise a bounded validation error."""
    if not GIT_SHA_RE.fullmatch(value):
        raise ValueError(f"{label} must be a full 40-character Git SHA")
    return value.lower()


def git_bytes(repo_root: Path, *args: str) -> bytes:
    """Run one read-only Git command and return its raw stdout."""
    resolved_root = repo_root.resolve(strict=True)
    completed = subprocess.run(
        [
            "git",
            "-c",
            f"safe.directory={resolved_root}",
            "-C",
            str(resolved_root),
            *args,
        ],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(detail or f"git {args[0]} failed")
    return completed.stdout


def safe_relative_path(raw_path: str) -> str | None:
    """Return a normalized repository path, rejecting traversal and drive paths."""
    posix_path = PurePosixPath(raw_path)
    windows_path = PureWindowsPath(raw_path)
    if (
        not raw_path
        or "\\" in raw_path
        or raw_path.startswith(("/", "//"))
        or posix_path.is_absolute()
        or windows_path.is_absolute()
        or bool(windows_path.drive)
        or ".." in posix_path.parts
        or raw_path != posix_path.as_posix()
    ):
        return None
    return raw_path


def changed_paths(changed_files_file: Path) -> list[str]:
    """Return unique safe paths from the trusted newline-delimited manifest."""
    paths: list[str] = []
    seen: set[str] = set()
    for raw_line in changed_files_file.read_bytes().splitlines():
        path = raw_line.decode("utf-8", errors="surrogateescape").strip()
        safe_path = safe_relative_path(path)
        if safe_path is None or safe_path in seen:
            continue
        paths.append(safe_path)
        seen.add(safe_path)
    return paths


def current_source_lines(repo_root: Path, path: str) -> list[bytes] | None:
    """Return bounded current-head line bytes for a safe regular repository file."""
    resolved_root = repo_root.resolve(strict=True)
    try:
        source_path = resolved_root.joinpath(*PurePosixPath(path).parts).resolve(
            strict=True
        )
        source_path.relative_to(resolved_root)
        source_stat = source_path.stat()
    except (OSError, ValueError):
        return None
    if not stat.S_ISREG(source_stat.st_mode) or source_stat.st_size > MAX_SOURCE_BYTES:
        return None
    try:
        return source_path.read_bytes().splitlines()
    except OSError:
        return None


def changed_line_numbers(
    repo_root: Path,
    base_sha: str,
    head_sha: str,
    path: str,
) -> list[int]:
    """Return the first and last current-head lines changed for one path."""
    diff = git_bytes(
        repo_root,
        "diff",
        "--unified=0",
        "--no-color",
        "--no-ext-diff",
        "--find-renames",
        base_sha,
        head_sha,
        "--",
        path,
    )
    first_line: int | None = None
    last_line: int | None = None
    for diff_line in diff.splitlines():
        match = HUNK_RE.match(diff_line)
        if match is None:
            continue
        start = int(match.group(1))
        count = int(match.group(2) or b"1")
        if count < 1:
            continue
        if first_line is None:
            first_line = start
        last_line = start + count - 1
    if first_line is None or last_line is None:
        return []
    return [first_line] if first_line == last_line else [first_line, last_line]


def select_bounded_lines(numbers: Sequence[int], limit: int) -> list[int]:
    """Select stable boundary-spanning line numbers within a per-file limit."""
    unique = sorted(set(numbers))
    if limit <= 0 or not unique:
        return []
    if len(unique) <= limit:
        return unique
    if limit == 1:
        return [unique[0]]
    selected = {
        unique[round(index * (len(unique) - 1) / (limit - 1))]
        for index in range(limit)
    }
    return sorted(selected)


def collect_receipts(
    repo_root: Path,
    base_sha: str,
    head_sha: str,
    paths: Sequence[str],
    *,
    lines_per_file: int = 2,
    max_receipts: int = 40,
) -> list[SourceLineReceipt]:
    """Collect bounded exact-line digests for current regular changed files."""
    base_sha = validate_git_sha(base_sha, "base SHA")
    head_sha = validate_git_sha(head_sha, "head SHA")
    if lines_per_file < 1 or max_receipts < 1:
        return []
    receipts: list[SourceLineReceipt] = []
    for raw_path in paths[:MAX_CHANGED_PATHS]:
        path = safe_relative_path(raw_path)
        if path is None:
            continue
        source_lines = current_source_lines(repo_root, path)
        if not source_lines:
            continue
        changed_lines = changed_line_numbers(repo_root, base_sha, head_sha, path)
        valid_lines = [
            line for line in changed_lines if 1 <= line <= len(source_lines)
        ]
        if not valid_lines:
            valid_lines = [1]
        for line in select_bounded_lines(valid_lines, lines_per_file):
            digest = hashlib.sha256(source_lines[line - 1]).hexdigest()
            receipts.append(SourceLineReceipt(path=path, line=line, digest=digest))
            if len(receipts) >= max_receipts:
                return receipts
    return receipts


def all_changed_hunk_lines(
    repo_root: Path,
    base_sha: str,
    head_sha: str,
    paths: Sequence[str],
) -> list[tuple[str, int]]:
    """Return every current-head line that belongs to a changed hunk."""
    base_sha = validate_git_sha(base_sha, "base SHA")
    head_sha = validate_git_sha(head_sha, "head SHA")
    rows: list[tuple[str, int]] = []
    for raw_path in paths[:MAX_CHANGED_PATHS]:
        path = safe_relative_path(raw_path)
        if path is None:
            continue
        diff = git_bytes(
            repo_root,
            "diff",
            "--unified=0",
            "--no-color",
            "--no-ext-diff",
            "--find-renames",
            base_sha,
            head_sha,
            "--",
            path,
        )
        for diff_line in diff.splitlines():
            match = HUNK_RE.match(diff_line)
            if match is None:
                continue
            start = int(match.group(1))
            count = int(match.group(2) or b"1")
            if count < 1:
                continue
            rows.extend((path, line) for line in range(start, start + count))
    return rows


def hunk_line_path_is_safe(path: str) -> bool:
    """Return whether a hunk-line path can appear in sealed review evidence."""
    posix_path = PurePosixPath(path)
    return not (
        not path
        or path.startswith("/")
        or ".." in posix_path.parts
        or posix_path.is_absolute()
        or any(character in path for character in ("`", "<", ">", "&", "\\", " ", "="))
        or any(token in path for token in ("-->", "<!--", "```"))
    )


def render_hunk_line_manifest(rows: Sequence[tuple[str, int]]) -> str:
    """Render a nonempty trusted ``path:line`` manifest for the normalizer."""
    safe_rows = [
        (path, line) for path, line in rows if hunk_line_path_is_safe(path)
    ]
    if not safe_rows:
        return "# no current-head hunk lines\n"
    return "".join(f"{path}:{line}\n" for path, line in safe_rows)


def render_hunk_line_evidence(rows: Sequence[tuple[str, int]]) -> str:
    """Render sealed-evidence tokens so hashed review-dispatch need not change."""
    lines = [
        "## Current-head changed hunk lines",
        "",
        (
            "The trusted workflow listed every RIGHT-side path and line from "
            "git diff --unified=0. REQUEST_CHANGES findings may cite only these "
            "lines so GitHub inline comments attach instead of returning HTTP 422."
        ),
        "",
    ]
    emitted = False
    for path, line in rows:
        if not hunk_line_path_is_safe(path):
            continue
        lines.append(f"OPENCODE_CHANGED_HUNK_LINE path={path} line={line}")
        emitted = True
    if not emitted:
        lines.append("OPENCODE_CHANGED_HUNK_LINE none")
    return "\n".join(lines)


def render_markdown(receipts: Sequence[SourceLineReceipt]) -> str:
    """Render injection-resistant trusted receipt evidence for the review model."""
    lines = [
        "## Adversarial probe source-line receipts",
        "",
        (
            "The trusted workflow computed these receipts from exact current-head "
            "changed-file bytes. Copy an exact path, line, and receipt into each "
            "probe evidence field; do not invent or recompute a receipt."
        ),
        (
            "A receipt proves only the cited source-line identity. The probe evidence "
            "must separately cite the trusted test, check, log, diff, or source-trace "
            "outcome that falsified or confirmed the concrete hypothesis."
        ),
        "",
    ]
    if not receipts:
        lines.append(
            "No eligible current-head regular changed-file line was available; "
            "approval must fail closed."
        )
        return "\n".join(lines)
    for receipt in receipts:
        payload = {
            "path": receipt.path,
            "line": receipt.line,
            "receipt": f"source-line-sha256={receipt.digest}",
        }
        serialized = json.dumps(payload, ensure_ascii=True, sort_keys=True)
        for character, escaped in (
            ("`", "\\u0060"),
            ("<", "\\u003c"),
            (">", "\\u003e"),
            ("&", "\\u0026"),
        ):
            serialized = serialized.replace(character, escaped)
        lines.append(f"- `{serialized}`")
    return "\n".join(lines)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments for trusted receipt generation."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--changed-files-file", required=True, type=Path)
    parser.add_argument("--hunk-lines-file", type=Path)
    parser.add_argument("--lines-per-file", type=int, default=2)
    parser.add_argument("--max-receipts", type=int, default=40)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Generate and print bounded trusted receipt evidence."""
    args = parse_args(argv)
    if args.lines_per_file not in {1, 2} or args.max_receipts < 1:
        print(
            "lines-per-file must be 1 or 2 and max-receipts must be positive",
            file=sys.stderr,
        )
        return 2
    try:
        paths = changed_paths(args.changed_files_file)
        receipts = collect_receipts(
            args.repo_root,
            args.base_sha,
            args.head_sha,
            paths,
            lines_per_file=args.lines_per_file,
            max_receipts=args.max_receipts,
        )
        hunk_rows = all_changed_hunk_lines(
            args.repo_root, args.base_sha, args.head_sha, paths
        )
        if args.hunk_lines_file is not None:
            args.hunk_lines_file.write_text(
                render_hunk_line_manifest(hunk_rows),
                encoding="utf-8",
            )
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"trusted adversarial receipt generation failed: {exc}", file=sys.stderr)
        return 2
    print(render_markdown(receipts))
    print()
    print(render_hunk_line_evidence(hunk_rows))
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through runpy CLI test
    raise SystemExit(main())
