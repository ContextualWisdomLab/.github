#!/usr/bin/env python3
"""Emit bounded trusted receipts for changed current-head source lines."""

from __future__ import annotations

import argparse
import hashlib
import re
import stat
import subprocess
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Sequence


SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
HUNK_RE = re.compile(rb"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
MAX_MANIFEST_BYTES = 1024 * 1024
MAX_SOURCE_BYTES = 2 * 1024 * 1024
DEFAULT_MAX_RECEIPTS_PER_FILE = 4
DEFAULT_MAX_TOTAL_RECEIPTS = 64
HARD_MAX_RECEIPTS_PER_FILE = 16
HARD_MAX_TOTAL_RECEIPTS = 256


class ReceiptError(RuntimeError):
    """Raised when trusted receipt generation cannot preserve its contract."""


class SourceUnavailable(ReceiptError):
    """Raised when one changed path has no safe current-head source lines."""


@dataclass(frozen=True, order=True)
class SourceLineReceipt:
    """One exact current-head line digest exposed to the isolated reviewer."""

    path: str
    line: int
    digest: str


def git_bytes(repo_root: Path, *args: str) -> bytes:
    """Run one read-only Git command and return its exact stdout bytes."""
    completed = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        command = args[0] if args else "command"
        raise ReceiptError(f"git {command} failed: {detail[:500] or 'no detail'}")
    return completed.stdout


def git_returncode(repo_root: Path, *args: str) -> tuple[int, str]:
    """Run one read-only Git predicate and return its status and bounded detail."""
    completed = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    detail = completed.stderr.decode("utf-8", errors="replace").strip()
    return completed.returncode, detail[:500]


def validated_sha(value: str, label: str) -> str:
    """Return one normalized immutable Git SHA or fail closed."""
    if not SHA_RE.fullmatch(value):
        raise ReceiptError(f"{label} must be a 40-character hexadecimal commit SHA")
    return value.casefold()


def validate_repository(repo_root: Path, diff_base: str, head_sha: str) -> Path:
    """Bind receipt generation to a clean checkout of the exact requested head."""
    diff_base = validated_sha(diff_base, "diff base")
    head_sha = validated_sha(head_sha, "head SHA")
    try:
        root = repo_root.resolve(strict=True)
    except OSError as exc:
        raise ReceiptError(f"repository root could not be resolved: {exc}") from exc
    if not root.is_dir():
        raise ReceiptError("repository root must be a directory")

    top_level = Path(
        git_bytes(root, "rev-parse", "--show-toplevel")
        .decode("utf-8", errors="strict")
        .strip()
    ).resolve(strict=True)
    if top_level != root:
        raise ReceiptError("repository root must be the Git worktree top level")

    actual_head = (
        git_bytes(root, "rev-parse", "--verify", "HEAD^{commit}")
        .decode("ascii", errors="strict")
        .strip()
        .casefold()
    )
    if actual_head != head_sha:
        raise ReceiptError(
            f"trusted worktree HEAD {actual_head} does not match requested head {head_sha}"
        )
    resolved_base = (
        git_bytes(root, "rev-parse", "--verify", f"{diff_base}^{{commit}}")
        .decode("ascii", errors="strict")
        .strip()
        .casefold()
    )
    if resolved_base != diff_base:
        raise ReceiptError(
            "diff base did not resolve to the requested immutable commit"
        )

    ancestor_status, ancestor_detail = git_returncode(
        root, "merge-base", "--is-ancestor", diff_base, head_sha
    )
    if ancestor_status == 1:
        raise ReceiptError("diff base is not an ancestor of the requested head")
    if ancestor_status != 0:
        raise ReceiptError(
            "could not verify diff-base ancestry: "
            + (ancestor_detail or f"git exited {ancestor_status}")
        )

    clean_status, clean_detail = git_returncode(
        root, "diff", "--quiet", "--no-ext-diff", head_sha, "--"
    )
    if clean_status == 1:
        raise ReceiptError(
            "trusted current-head worktree contains tracked modifications"
        )
    if clean_status != 0:
        raise ReceiptError(
            "could not verify current-head worktree cleanliness: "
            + (clean_detail or f"git exited {clean_status}")
        )
    return root


def safe_changed_path(value: str) -> str:
    """Validate one repository-relative path before using or rendering it."""
    if not value or value != value.strip() or len(value.encode("utf-8")) > 4096:
        raise ReceiptError("changed-file manifest contains an empty or oversized path")
    if "\\" in value or "`" in value:
        raise ReceiptError(f"changed-file manifest contains an unsafe path: {value!r}")
    if any(unicodedata.category(character).startswith("C") for character in value):
        raise ReceiptError(
            f"changed-file manifest contains control characters: {value!r}"
        )

    posix_path = PurePosixPath(value)
    if (
        value.startswith(("/", "//"))
        or posix_path.is_absolute()
        or ".." in posix_path.parts
        or "." in posix_path.parts
        or not posix_path.parts
        or posix_path.parts[0] == ".git"
        or posix_path.as_posix() != value
    ):
        raise ReceiptError(f"changed-file manifest contains an unsafe path: {value!r}")
    return value


def load_changed_paths(manifest_path: Path) -> tuple[str, ...]:
    """Read a bounded newline-delimited current-head changed-file manifest."""
    try:
        if manifest_path.is_symlink():
            raise ReceiptError("changed-file manifest must not be a symlink")
        manifest_stat = manifest_path.stat()
        if not stat.S_ISREG(manifest_stat.st_mode):
            raise ReceiptError("changed-file manifest must be a regular file")
        if manifest_stat.st_size > MAX_MANIFEST_BYTES:
            raise ReceiptError("changed-file manifest exceeds the bounded 1 MiB limit")
        manifest_text = manifest_path.read_text(encoding="utf-8", errors="strict")
    except ReceiptError:
        raise
    except (OSError, UnicodeError) as exc:
        raise ReceiptError(f"changed-file manifest could not be read: {exc}") from exc

    paths: list[str] = []
    seen: set[str] = set()
    for raw_line in manifest_text.splitlines():
        path = safe_changed_path(raw_line)
        if path in seen:
            raise ReceiptError(
                f"changed-file manifest contains a duplicate path: {path}"
            )
        seen.add(path)
        paths.append(path)
    return tuple(paths)


def diff_paths(
    repo_root: Path, diff_base: str, head_sha: str, diff_filter: str
) -> frozenset[str]:
    """Return exact UTF-8 paths from one bounded immutable Git diff."""
    raw_paths = git_bytes(
        repo_root,
        "diff",
        "--name-only",
        "-z",
        "--find-renames",
        f"--diff-filter={diff_filter}",
        "--no-ext-diff",
        "--no-textconv",
        diff_base,
        head_sha,
    )
    paths: set[str] = set()
    for raw_path in raw_paths.split(b"\0"):
        if not raw_path:
            continue
        try:
            path = raw_path.decode("utf-8", errors="strict")
        except UnicodeError as exc:
            raise ReceiptError("Git diff contains a non-UTF-8 path") from exc
        paths.add(safe_changed_path(path))
    return frozenset(paths)


def changed_line_numbers(
    repo_root: Path,
    diff_base: str,
    head_sha: str,
    path: str,
    *,
    limit: int,
) -> tuple[int, ...]:
    """Return bounded first/last current-head line numbers from zero-context hunks."""
    diff = git_bytes(
        repo_root,
        "diff",
        "--unified=0",
        "--no-color",
        "--no-ext-diff",
        "--no-textconv",
        "--find-renames",
        diff_base,
        head_sha,
        "--",
        path,
    )
    candidates: list[int] = []
    seen: set[int] = set()
    for diff_line in diff.splitlines():
        match = HUNK_RE.match(diff_line)
        if match is None:
            continue
        start = int(match.group(1))
        count = int(match.group(2) or b"1")
        if count <= 0:
            continue
        for line in (start, start + count - 1):
            if line <= 0 or line in seen:
                continue
            seen.add(line)
            candidates.append(line)
            if len(candidates) >= limit:
                return tuple(candidates)
    return tuple(candidates)


def source_lines(repo_root: Path, path: str) -> tuple[bytes, ...]:
    """Read safe regular current-head line bytes with normalizer-identical splitting."""
    relative = PurePosixPath(path)
    candidate = repo_root.joinpath(*relative.parts)
    cursor = repo_root
    try:
        for part in relative.parts:
            cursor = cursor / part
            if cursor.is_symlink():
                raise SourceUnavailable("path is a symlink")
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(repo_root)
        source_stat = resolved.stat()
        if not stat.S_ISREG(source_stat.st_mode):
            raise SourceUnavailable("path is not a regular current-head source file")
        if source_stat.st_size > MAX_SOURCE_BYTES:
            raise SourceUnavailable(
                "source file exceeds the bounded 2 MiB receipt limit"
            )
        source_bytes = resolved.read_bytes()
    except SourceUnavailable:
        raise
    except (OSError, ValueError) as exc:
        raise SourceUnavailable(f"source path could not be read safely: {exc}") from exc

    if b"\0" in source_bytes[:8192]:
        raise SourceUnavailable("source file is binary")
    lines = tuple(source_bytes.splitlines())
    if not lines:
        raise SourceUnavailable("source file has no current-head lines")
    return lines


def first_nonempty_line(lines: Sequence[bytes]) -> int:
    """Return a stable fallback line for rename-only or mode-only changes."""
    for line_number, line in enumerate(lines, start=1):
        if line.strip():
            return line_number
    return 1


def source_line_receipt(
    path: str, line: int, lines: Sequence[bytes]
) -> SourceLineReceipt:
    """Hash exact line bytes without a line ending, matching the trusted normalizer."""
    if line <= 0 or line > len(lines):
        raise ReceiptError(
            f"diff line {line} for {path} is outside current-head file length {len(lines)}"
        )
    digest = hashlib.sha256(lines[line - 1]).hexdigest()
    return SourceLineReceipt(path=path, line=line, digest=digest)


def collect_receipts(
    repo_root: Path,
    diff_base: str,
    head_sha: str,
    changed_files: Path,
    *,
    max_per_file: int = DEFAULT_MAX_RECEIPTS_PER_FILE,
    max_total: int = DEFAULT_MAX_TOTAL_RECEIPTS,
) -> tuple[tuple[SourceLineReceipt, ...], tuple[str, ...]]:
    """Collect bounded receipts and visible non-fatal unavailability reasons."""
    if not 1 <= max_per_file <= HARD_MAX_RECEIPTS_PER_FILE:
        raise ReceiptError(
            f"max_per_file must be between 1 and {HARD_MAX_RECEIPTS_PER_FILE}"
        )
    if not 1 <= max_total <= HARD_MAX_TOTAL_RECEIPTS:
        raise ReceiptError(f"max_total must be between 1 and {HARD_MAX_TOTAL_RECEIPTS}")

    normalized_base = validated_sha(diff_base, "diff base")
    normalized_head = validated_sha(head_sha, "head SHA")
    root = validate_repository(repo_root, normalized_base, normalized_head)
    manifest_paths = load_changed_paths(changed_files)
    current_paths = diff_paths(root, normalized_base, normalized_head, "ACMR")
    deleted_paths = diff_paths(root, normalized_base, normalized_head, "D")

    receipts: list[SourceLineReceipt] = []
    notices: list[str] = []
    for path in sorted(manifest_paths):
        if path in deleted_paths:
            notices.append(f"{path}: deleted paths have no current-head source line")
            continue
        if path not in current_paths:
            raise ReceiptError(
                f"changed-file manifest path is absent from the immutable diff: {path}"
            )
        try:
            lines = source_lines(root, path)
        except SourceUnavailable as exc:
            notices.append(f"{path}: {exc}")
            continue

        line_numbers = changed_line_numbers(
            root,
            normalized_base,
            normalized_head,
            path,
            limit=max_per_file,
        )
        if not line_numbers:
            line_numbers = (first_nonempty_line(lines),)
        for line in line_numbers:
            if len(receipts) >= max_total:
                notices.append(
                    f"receipt output truncated at the global {max_total}-receipt limit"
                )
                return tuple(receipts), tuple(notices)
            receipts.append(source_line_receipt(path, line, lines))
    return tuple(receipts), tuple(notices)


def render_markdown(
    receipts: Sequence[SourceLineReceipt], notices: Sequence[str], head_sha: str
) -> str:
    """Render a bounded receipt packet without exposing untrusted source bodies."""
    lines = [
        f"- Result: {'PASS' if receipts else 'UNAVAILABLE'}",
        f"- Head SHA: `{validated_sha(head_sha, 'head SHA')}`",
        "- Semantics: each digest is SHA-256 of the exact cited current-head line bytes without its line ending.",
        "- Scope: a receipt proves source-line binding only; it does not prove test, command, browser, or runtime execution.",
        "- Model rule: copy exactly one receipt for the same cited path and line; never compute, alter, or invent a digest.",
    ]
    if receipts:
        lines.extend(
            f"- `{receipt.path}:{receipt.line}` `source-line-sha256={receipt.digest}`"
            for receipt in receipts
        )
    else:
        lines.append(
            "- Reason: no safe current-head text line was eligible for a trusted receipt."
        )
    lines.extend(f"- Notice: {notice}" for notice in notices)
    return "\n".join(lines) + "\n"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line inputs for trusted receipt generation."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--diff-base", required=True)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--changed-files", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Emit trusted receipt evidence and fail visibly when none can be produced."""
    args = parse_args(argv)
    try:
        receipts, notices = collect_receipts(
            args.repo_root,
            args.diff_base,
            args.head_sha,
            args.changed_files,
        )
        rendered = render_markdown(receipts, notices, args.head_sha)
    except ReceiptError as exc:
        print(f"Trusted source-line receipt generation failed: {exc}", file=sys.stderr)
        return 1
    sys.stdout.write(rendered)
    if not receipts:
        print(
            "Trusted source-line receipt generation produced no eligible current-head lines.",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
