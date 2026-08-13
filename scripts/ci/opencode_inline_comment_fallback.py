#!/usr/bin/env python3
"""Filter inline comments to current-head hunks and cite refused path:line."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

DEFAULT_SINGLE_COMMENT_RETRY_LIMIT = 20
ERROR_PHRASE_MAX_CHARS = 240
LEFTOVER_DIFF_REASONS = frozenset({"LEFT", "cannot-provide"})
HTTP_422_LINE_RE = re.compile(r"(?im)^(?:gh:\s*)?(.*HTTP 422.*)$")
HUNK_HEADER_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
PLUS_PATH_RE = re.compile(r"^\+\+\+ b/(.+?)(?:\t.*)?$")
MINUS_PATH_RE = re.compile(r"^--- a/(.+?)(?:\t.*)?$")
DIFF_FENCE_RE = re.compile(r"```diff\r?\n(.*?)```", re.DOTALL)
SUGGESTION_FENCE_RE = re.compile(r"```suggestion\r?\n(.*?)```", re.DOTALL)


def safe_finding_path(raw_path: object) -> str | None:
    """Return a repository-relative finding path, or None when it is unsafe."""
    if not isinstance(raw_path, str):
        return None
    path = raw_path.strip()
    posix_path = PurePosixPath(path)
    windows_path = PureWindowsPath(path)
    if (
        not path
        or "\\" in path
        or path.startswith(("/", "//"))
        or posix_path.is_absolute()
        or windows_path.is_absolute()
        or bool(windows_path.drive)
        or ".." in posix_path.parts
        or path != posix_path.as_posix()
    ):
        return None
    return path


def safe_finding_line(raw_line: object) -> int | None:
    """Return a positive integer finding line, or None when it is not one."""
    if isinstance(raw_line, bool) or not isinstance(raw_line, int) or raw_line <= 0:
        return None
    return raw_line


def trusted_finding_locations(control: dict[str, Any]) -> list[tuple[str, int]]:
    """Return unique sanitized finding path:line pairs in first-seen order."""
    findings = control.get("findings")
    if not isinstance(findings, list):
        return []
    locations: list[tuple[str, int]] = []
    seen: set[tuple[str, int]] = set()
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        path = safe_finding_path(finding.get("path"))
        line = safe_finding_line(finding.get("line"))
        if path is None or line is None:
            continue
        location = (path, line)
        if location in seen:
            continue
        seen.add(location)
        locations.append(location)
    return locations


def parse_refused_receipts(text: str) -> list[tuple[str, int, str]]:
    """Parse ``path:line`` or ``path:line<TAB>phrase`` retry-failure rows."""
    receipts: list[tuple[str, int, str]] = []
    seen: set[tuple[str, int]] = set()
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        loc_text, _sep, phrase = line.partition("\t")
        if ":" not in loc_text:
            continue
        path_text, _, line_text = loc_text.rpartition(":")
        path = safe_finding_path(path_text)
        try:
            parsed_line = int(line_text)
        except ValueError:
            parsed_line = 0
        line_number = safe_finding_line(parsed_line)
        if path is None or line_number is None:
            continue
        location = (path, line_number)
        if location in seen:
            continue
        seen.add(location)
        receipts.append((path, line_number, phrase.strip()))
    return receipts


def parse_refused_locations(text: str) -> list[tuple[str, int]]:
    """Parse ``path:line`` rows from one-at-a-time retry failures."""
    return [(path, line) for path, line, _phrase in parse_refused_receipts(text)]


def single_comment_retry_limit(raw: object | None = None) -> int:
    """Return a positive one-at-a-time retry cap, defaulting to 20."""
    if raw is None:
        raw = os.environ.get("OPENCODE_INLINE_COMMENT_RETRY_LIMIT")
    if isinstance(raw, bool):
        return DEFAULT_SINGLE_COMMENT_RETRY_LIMIT
    if isinstance(raw, int) and raw > 0:
        return raw
    if isinstance(raw, str):
        text = raw.strip()
        if text.isdigit():
            value = int(text)
            if value > 0:
                return value
    return DEFAULT_SINGLE_COMMENT_RETRY_LIMIT


def record_refused_receipt(
    dest: Path, path: str, line: int, error_text: str
) -> None:
    """Append one refused ``path:line`` and its GitHub 422 phrase."""
    safe_path = safe_finding_path(path)
    safe_line = safe_finding_line(line)
    if safe_path is None or safe_line is None:
        return
    phrase = github_publication_error_phrase(error_text)
    with dest.open("a", encoding="utf-8") as handle:
        handle.write(f"{safe_path}:{safe_line}\t{phrase}\n")


def _hunk_side_lines(start_text: str, count_text: str | None) -> set[int]:
    """Return inclusive new- or old-file line numbers for one unified hunk side."""
    start = int(start_text)
    count = int(count_text) if count_text is not None else 1
    if count < 1:
        return set()
    return set(range(start, start + count))


def _diff_path(raw_path: str) -> str | None:
    """Return a safe repository path from a unified-diff a/ or b/ suffix."""
    return safe_finding_path(raw_path.strip().strip('"'))


def parse_unified_diff_hunk_lines(
    diff_text: str,
) -> dict[str, dict[str, set[int]]]:
    """Return LEFT/RIGHT commentable lines for each path in a unified diff."""
    hunks: dict[str, dict[str, set[int]]] = {}
    current_left: str | None = None
    current_right: str | None = None
    for raw in (diff_text or "").splitlines():
        if raw.startswith("+++ "):
            match = PLUS_PATH_RE.match(raw)
            current_right = _diff_path(match.group(1)) if match else None
            continue
        if raw.startswith("--- "):
            match = MINUS_PATH_RE.match(raw)
            current_left = _diff_path(match.group(1)) if match else None
            continue
        header = HUNK_HEADER_RE.match(raw)
        if header is None:
            continue
        left_lines = _hunk_side_lines(header.group(1), header.group(2))
        right_lines = _hunk_side_lines(header.group(3), header.group(4))
        if current_left and left_lines:
            bucket = hunks.setdefault(current_left, {"LEFT": set(), "RIGHT": set()})
            bucket["LEFT"].update(left_lines)
        if current_right and right_lines:
            bucket = hunks.setdefault(current_right, {"LEFT": set(), "RIGHT": set()})
            bucket["RIGHT"].update(right_lines)
    return hunks


def comment_on_changed_hunk(
    path: str,
    line: int,
    hunks: dict[str, dict[str, set[int]]],
    *,
    side: str = "RIGHT",
) -> bool:
    """Return whether ``path:line`` sits on a current-head changed hunk."""
    safe_path = safe_finding_path(path)
    safe_line = safe_finding_line(line)
    if safe_path is None or safe_line is None:
        return False
    side_key = side if side in {"LEFT", "RIGHT"} else "RIGHT"
    return safe_line in hunks.get(safe_path, {}).get(side_key, set())


def filter_payload_comments_to_hunks(
    payload: dict[str, Any],
    hunks: dict[str, dict[str, set[int]]],
) -> tuple[dict[str, Any], list[tuple[str, int]]]:
    """Keep only comments whose path:line sits on a current-head changed hunk."""
    comments = payload.get("comments")
    if not hunks or not isinstance(comments, list):
        return payload, []
    kept: list[Any] = []
    skipped: list[tuple[str, int]] = []
    seen: set[tuple[str, int]] = set()
    for comment in comments:
        if not isinstance(comment, dict):
            continue
        path = safe_finding_path(comment.get("path"))
        line = safe_finding_line(comment.get("line"))
        if path is None or line is None:
            continue
        side = comment.get("side")
        side_key = side if side in {"LEFT", "RIGHT"} else "RIGHT"
        if comment_on_changed_hunk(path, line, hunks, side=side_key):
            kept.append(comment)
            continue
        location = (path, line)
        if location in seen:
            continue
        seen.add(location)
        skipped.append(location)
    filtered = dict(payload)
    filtered["comments"] = kept
    return filtered, skipped


def extract_suggestion_replacement(diff_text: str) -> str | None:
    """Return GitHub suggestion replacement lines from a unified suggested_diff."""
    raw = (diff_text or "").replace("\r\n", "\n")
    stripped = raw.strip()
    if not stripped:
        return None
    lowered = stripped.casefold()
    if lowered.startswith("n/a") or lowered.startswith("cannot provide"):
        return None
    plus_lines: list[str] = []
    saw_diff_marker = False
    for line in raw.splitlines():
        if line.startswith(("diff ", "index ", "---", "+++", "@@")):
            saw_diff_marker = True
            continue
        if line.startswith("+"):
            plus_lines.append(line[1:])
            saw_diff_marker = True
            continue
        if line.startswith("-"):
            saw_diff_marker = True
    if plus_lines:
        replacement = "\n".join(plus_lines)
        if "```" in replacement:
            return None
        return replacement
    if saw_diff_marker:
        return None
    if "```" in stripped:
        return None
    return stripped.strip("\n")


def render_github_suggestion_block(replacement: str) -> str:
    """Return one GitHub apply-suggestion fence for replacement lines."""
    return f"```suggestion\n{replacement}\n```"


def body_has_diff_fence(body: str) -> bool:
    """Return True when ``body`` contains a closed `` ```diff `` fence."""
    return DIFF_FENCE_RE.search(body) is not None


def body_has_suggestion_fence(body: str) -> bool:
    """Return True when ``body`` contains a closed `` ```suggestion `` fence."""
    return SUGGESTION_FENCE_RE.search(body) is not None


def count_removed_suggestion_lines(diff_text: str) -> int:
    """Return how many current-file lines a unified suggested_diff removes."""
    count = 0
    for line in (diff_text or "").splitlines():
        if line.startswith(("diff ", "index ", "---", "+++", "@@")):
            continue
        if line.startswith("-"):
            count += 1
    return count


def suggestion_comment_range(
    path: str,
    line: int,
    diff_text: str,
    hunks: dict[str, dict[str, set[int]]] | None,
    *,
    side: str = "RIGHT",
) -> tuple[int | None, int]:
    """Return ``(start_line, end_line)`` when a multi-line hunk range is safe."""
    safe_path = safe_finding_path(path)
    safe_line = safe_finding_line(line)
    if safe_path is None or safe_line is None:
        fallback = line if isinstance(line, int) and not isinstance(line, bool) and line > 0 else 1
        return None, fallback
    removed = count_removed_suggestion_lines(diff_text)
    if removed <= 1 or not hunks:
        return None, safe_line
    end = safe_line + removed - 1
    side_key = side if side in {"LEFT", "RIGHT"} else "RIGHT"
    hunk_lines = hunks.get(safe_path, {}).get(side_key, set())
    if all(candidate in hunk_lines for candidate in range(safe_line, end + 1)):
        return safe_line, end
    return None, safe_line


def apply_github_suggestion_blocks(
    payload: dict[str, Any],
    hunks: dict[str, dict[str, set[int]]] | None = None,
) -> dict[str, Any]:
    """Append GitHub suggestion fences and multi-line ranges on surviving comments."""
    comments = payload.get("comments")
    if not isinstance(comments, list):
        return payload
    updated: list[Any] = []
    for comment in comments:
        if not isinstance(comment, dict):
            updated.append(comment)
            continue
        body = comment.get("body")
        side = comment.get("side")
        if not isinstance(body, str) or side == "LEFT":
            updated.append(comment)
            continue
        replacement: str | None = None
        diff_text: str | None = None
        for match in DIFF_FENCE_RE.finditer(body):
            candidate = extract_suggestion_replacement(match.group(1))
            if candidate is not None:
                replacement = candidate
                diff_text = match.group(1)
                break
        new_comment = dict(comment)
        if replacement is not None:
            if not body_has_suggestion_fence(body):
                new_comment["body"] = (
                    f"{body.rstrip()}\n\n{render_github_suggestion_block(replacement)}\n"
                )
            path = safe_finding_path(comment.get("path"))
            line = safe_finding_line(comment.get("line"))
            side_key = side if side in {"LEFT", "RIGHT"} else "RIGHT"
            if path is not None and line is not None:
                start, end = suggestion_comment_range(
                    path, line, diff_text or "", hunks, side=side_key
                )
                if start is not None:
                    new_comment["start_line"] = start
                    new_comment["line"] = end
                    new_comment["start_side"] = side_key
        updated.append(new_comment)
    rewritten = dict(payload)
    rewritten["comments"] = updated
    return rewritten


def format_applyable_range(path: str, start: int, end: int) -> str:
    """Return ``path:line`` or ``path:start-end`` for one applyable suggestion."""
    if start == end:
        return f"{path}:{start}"
    return f"{path}:{start}-{end}"


def parse_applyable_ranges(text: str) -> list[tuple[str, int, int]]:
    """Parse ``path:line`` or ``path:start-end`` applyable-suggestion rows."""
    ranges: list[tuple[str, int, int]] = []
    seen: set[tuple[str, int, int]] = set()
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        loc_text, _sep, _phrase = line.partition("\t")
        if ":" not in loc_text:
            continue
        path_text, _, rest = loc_text.rpartition(":")
        path = safe_finding_path(path_text)
        if path is None:
            continue
        if "-" in rest:
            start_text, _, end_text = rest.partition("-")
            try:
                start_value = int(start_text)
                end_value = int(end_text)
            except ValueError:
                continue
        else:
            try:
                start_value = end_value = int(rest)
            except ValueError:
                continue
        start = safe_finding_line(start_value)
        end = safe_finding_line(end_value)
        if start is None or end is None or end < start:
            continue
        key = (path, start, end)
        if key in seen:
            continue
        seen.add(key)
        ranges.append(key)
    return ranges


def applyable_suggestion_ranges(
    payload: dict[str, Any],
) -> list[tuple[str, int, int]]:
    """Return ``(path, start, end)`` for comments that carry a suggestion fence."""
    comments = payload.get("comments")
    if not isinstance(comments, list):
        return []
    ranges: list[tuple[str, int, int]] = []
    seen: set[tuple[str, int, int]] = set()
    for comment in comments:
        if not isinstance(comment, dict):
            continue
        body = comment.get("body")
        if (
            not isinstance(body, str)
            or comment.get("side") == "LEFT"
            or not body_has_suggestion_fence(body)
        ):
            continue
        path = safe_finding_path(comment.get("path"))
        end = safe_finding_line(comment.get("line"))
        start_raw = comment.get("start_line")
        start = safe_finding_line(start_raw) if start_raw is not None else end
        if path is None or end is None or start is None:
            continue
        if start > end:
            start, end = end, start
        key = (path, start, end)
        if key in seen:
            continue
        seen.add(key)
        ranges.append(key)
    return ranges


def render_applyable_receipts(ranges: list[tuple[str, int, int]]) -> list[str]:
    """Return overview receipt lines for applyable suggestion ranges."""
    return [f"- `{format_applyable_range(path, start, end)}`" for path, start, end in ranges]


def leftover_diff_fence_reason(comment: dict[str, Any]) -> str | None:
    """Return ``LEFT`` or ``cannot-provide`` when a comment kept only a diff fence."""
    body = comment.get("body")
    if not isinstance(body, str):
        return None
    has_diff = body_has_diff_fence(body)
    has_suggestion = body_has_suggestion_fence(body)
    if comment.get("side") == "LEFT":
        if has_diff or has_suggestion:
            return "LEFT"
        return None
    if has_diff and not has_suggestion:
        return "cannot-provide"
    return None


def leftover_diff_fence_receipts(
    payload: dict[str, Any],
) -> list[tuple[str, int, str]]:
    """Return ``(path, line, reason)`` for comments that kept only a `` ```diff `` fence."""
    comments = payload.get("comments")
    if not isinstance(comments, list):
        return []
    receipts: list[tuple[str, int, str]] = []
    seen: set[tuple[str, int]] = set()
    for comment in comments:
        if not isinstance(comment, dict):
            continue
        reason = leftover_diff_fence_reason(comment)
        if reason is None:
            continue
        path = safe_finding_path(comment.get("path"))
        line = safe_finding_line(comment.get("line"))
        if path is None or line is None:
            continue
        key = (path, line)
        if key in seen:
            continue
        seen.add(key)
        receipts.append((path, line, reason))
    return receipts


def parse_leftover_diff_receipts(text: str) -> list[tuple[str, int, str]]:
    """Parse ``path:line<TAB>LEFT|cannot-provide`` leftover-diff rows."""
    return [
        (path, line, phrase)
        for path, line, phrase in parse_refused_receipts(text)
        if phrase in LEFTOVER_DIFF_REASONS
    ]


def render_leftover_diff_receipts(
    receipts: list[tuple[str, int, str]],
) -> list[str]:
    """Return overview receipt lines for leftover `` ```diff `` fences."""
    return [f"- `{path}:{line}` — {reason}" for path, line, reason in receipts]


def write_hunk_filtered_payload(
    payload: dict[str, Any],
    hunks: dict[str, dict[str, set[int]]],
    output: Path,
    skipped_path: Path | None = None,
    applyable_path: Path | None = None,
    leftover_path: Path | None = None,
) -> int:
    """Write a hunk-filtered review payload and optional skipped ``path:line`` rows."""
    filtered, skipped = filter_payload_comments_to_hunks(payload, hunks)
    filtered = apply_github_suggestion_blocks(filtered, hunks)
    comments = filtered.get("comments")
    output.write_text(json.dumps(filtered, ensure_ascii=True), encoding="utf-8")
    if skipped_path is not None:
        skipped_path.write_text(
            "".join(f"{path}:{line}\n" for path, line in skipped),
            encoding="utf-8",
        )
    if applyable_path is not None:
        applyable_path.write_text(
            "".join(
                f"{format_applyable_range(path, start, end)}\n"
                for path, start, end in applyable_suggestion_ranges(filtered)
            ),
            encoding="utf-8",
        )
    if leftover_path is not None:
        leftover_path.write_text(
            "".join(
                f"{path}:{line}\t{reason}\n"
                for path, line, reason in leftover_diff_fence_receipts(filtered)
            ),
            encoding="utf-8",
        )
    return len(comments) if isinstance(comments, list) else 0


def record_attached_receipt(dest: Path, path: str, line: int) -> None:
    """Append one attached ``path:line`` row."""
    safe_path = safe_finding_path(path)
    safe_line = safe_finding_line(line)
    if safe_path is None or safe_line is None:
        return
    with dest.open("a", encoding="utf-8") as handle:
        handle.write(f"{safe_path}:{safe_line}\n")


def _collapse_error_text(text: str) -> str:
    """Return one-line error text without URLs or extra whitespace."""
    without_urls = re.sub(r"https?://\S+", "", text)
    return " ".join(without_urls.split())


def github_publication_error_phrase(text: str) -> str:
    """Return a bounded GitHub 422 phrase from ``gh api`` stderr or JSON."""
    raw = text or ""
    messages: list[str] = []
    seen: set[str] = set()
    decoder = json.JSONDecoder()
    index = 0
    while index < len(raw):
        start = raw.find("{", index)
        if start < 0:
            break
        try:
            value, consumed = decoder.raw_decode(raw[start:])
        except json.JSONDecodeError:
            index = start + 1
            continue
        index = start + consumed
        errors = value.get("errors")
        if not isinstance(errors, list):
            continue
        for item in errors:
            if not isinstance(item, dict) or not isinstance(item.get("message"), str):
                continue
            message = _collapse_error_text(item["message"])
            if not message or message in seen:
                continue
            seen.add(message)
            messages.append(message)
    if messages:
        return f"GitHub HTTP 422: {'; '.join(messages)}"[:ERROR_PHRASE_MAX_CHARS]
    match = HTTP_422_LINE_RE.search(raw)
    if match:
        line = _collapse_error_text(match.group(1))
        if line.casefold().startswith("github http 422"):
            return line[:ERROR_PHRASE_MAX_CHARS]
        return f"GitHub HTTP 422: {line}".rstrip(": ")[:ERROR_PHRASE_MAX_CHARS]
    if "422" in raw:
        return "GitHub HTTP 422"
    return "GitHub review write failed"


def github_error_is_unprocessable(text: str) -> bool:
    """Return whether GitHub rejected the review write as HTTP 422."""
    raw = text or ""
    if "422" in raw or "Unprocessable Entity" in raw:
        return True
    return "422" in github_publication_error_phrase(raw)


def iter_single_comment_payloads(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Return safe single-comment slices from a batch review payload."""
    comments = payload.get("comments")
    commit_id = payload.get("commit_id")
    if not isinstance(comments, list) or not isinstance(commit_id, str):
        return []
    commit_id = commit_id.strip()
    if not commit_id:
        return []
    singles: list[dict[str, Any]] = []
    for comment in comments:
        if not isinstance(comment, dict):
            continue
        path = safe_finding_path(comment.get("path"))
        line = safe_finding_line(comment.get("line"))
        body = comment.get("body")
        if path is None or line is None or not isinstance(body, str) or not body.strip():
            continue
        side = comment.get("side")
        singles.append(
            {
                "path": path,
                "line": line,
                "side": side if side in {"LEFT", "RIGHT"} else "RIGHT",
                "body": body,
                "commit_id": commit_id,
            }
        )
    return singles


def render_single_comment_review(
    item: dict[str, Any],
    *,
    event: str,
    review_body: str,
) -> dict[str, Any]:
    """Return one GitHub review payload that carries a single inline comment."""
    return {
        "event": event,
        "body": review_body,
        "commit_id": item["commit_id"],
        "comments": [
            {
                "path": item["path"],
                "line": item["line"],
                "side": item["side"],
                "body": item["body"],
            }
        ],
    }


def write_single_comment_payloads(
    payload: dict[str, Any],
    output_dir: Path,
    limit: int | None = None,
    deferred_path: Path | None = None,
) -> int:
    """Write at most ``limit`` COMMENT payloads and leftover ``path:line`` rows."""
    items = iter_single_comment_payloads(payload)
    cap = single_comment_retry_limit(limit)
    output_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    for index, item in enumerate(items[:cap]):
        path = output_dir / f"comment-{index:03d}.json"
        path.write_text(
            json.dumps(
                render_single_comment_review(item, event="COMMENT", review_body=""),
                ensure_ascii=True,
            ),
            encoding="utf-8",
        )
        count += 1
    if deferred_path is not None:
        deferred_path.write_text(
            "".join(f"{item['path']}:{item['line']}\n" for item in items[cap:]),
            encoding="utf-8",
        )
    return count


def render_inline_comment_receipts(
    locations: list[tuple[str, int]],
    error_phrase: str = "",
    phrases: dict[tuple[str, int], str] | None = None,
) -> list[str]:
    """Return durable overview receipt lines for refused inline comments."""
    if not locations:
        return []
    lines: list[str] = []
    for path, line in locations:
        phrase = ""
        if phrases is not None:
            phrase = phrases.get((path, line), "")
        if not phrase:
            phrase = error_phrase
        if phrase:
            lines.append(f"- `{path}:{line}` — {phrase}")
        else:
            lines.append(f"- `{path}:{line}`")
    return lines


def render_inline_comment_failure_suffix(
    locations: list[tuple[str, int]],
    *,
    error_phrase: str = "",
    mixed_success: bool = False,
    phrases: dict[tuple[str, int], str] | None = None,
    attached_locations: list[tuple[str, int]] | None = None,
    deferred_locations: list[tuple[str, int]] | None = None,
    skipped_locations: list[tuple[str, int]] | None = None,
    applyable_locations: list[tuple[str, int, int]] | None = None,
    leftover_locations: list[tuple[str, int, str]] | None = None,
    retry_limit: int | None = None,
) -> str:
    """Return the PR-body suffix used when GitHub rejects inline comments."""
    attached = attached_locations or []
    deferred = deferred_locations or []
    skipped = skipped_locations or []
    applyable = applyable_locations or []
    leftover = leftover_locations or []
    heading = (
        "## Inline comment publication receipts"
        if (
            error_phrase
            or mixed_success
            or attached
            or deferred
            or skipped
            or applyable
            or leftover
        )
        else "## Inline comment publishing failed"
    )
    lines = [
        "",
        heading,
        "",
    ]
    if attached:
        lines.append("GitHub accepted these trusted current-head finding locations:")
        lines.append("")
        lines.extend(render_inline_comment_receipts(attached))
        lines.append("")
    if locations:
        if mixed_success:
            if attached:
                lines.append(
                    "These trusted current-head finding locations were still refused:"
                )
            else:
                lines.append(
                    "GitHub accepted some inline comments. These trusted "
                    "current-head finding locations were still refused:"
                )
        else:
            lines.append(
                "GitHub did not accept the inline review comments for these "
                "trusted current-head finding locations:"
            )
        lines.append("")
        lines.extend(
            render_inline_comment_receipts(
                locations, error_phrase, phrases=phrases
            )
        )
        lines.append("")
        lines.append(
            "OpenCode did not copy suggested diffs into this PR-level body. "
            "Re-run the review after those exact path:line anchors sit on "
            "current-head changed hunks, or inspect the workflow log/control "
            "JSON and apply the changes manually."
        )
    elif not attached and not deferred and not skipped and not applyable and not leftover:
        lines.append(
            "GitHub did not accept the inline review comments, and the "
            "control JSON had no trusted path:line findings. Inspect the "
            "workflow log and apply any remaining blockers from the review "
            "body manually."
        )
        if error_phrase:
            lines.append("")
            lines.append(f"- GitHub error: {error_phrase}")
    if deferred:
        if locations or attached:
            lines.append("")
        lines.append(
            "These trusted current-head finding locations were not retried "
            f"(retry limit {single_comment_retry_limit(retry_limit)}):"
        )
        lines.append("")
        lines.extend(render_inline_comment_receipts(deferred))
        if not locations:
            lines.append("")
            lines.append(
                "OpenCode did not copy suggested diffs into this PR-level body. "
                "Re-run the review after those exact path:line anchors sit on "
                "current-head changed hunks, or inspect the workflow log/control "
                "JSON and apply the changes manually."
            )
    if skipped:
        if locations or attached or deferred:
            lines.append("")
        lines.append(
            "These trusted current-head finding locations were not posted "
            "because they sit outside every current-head changed hunk:"
        )
        lines.append("")
        lines.extend(render_inline_comment_receipts(skipped))
        if not locations and not deferred:
            lines.append("")
            lines.append(
                "OpenCode did not copy suggested diffs into this PR-level body. "
                "Re-run the review after those exact path:line anchors sit on "
                "current-head changed hunks, or inspect the workflow log/control "
                "JSON and apply the changes manually."
            )
    if applyable:
        if locations or attached or deferred or skipped:
            lines.append("")
        lines.append("GitHub can apply these suggested replacements:")
        lines.append("")
        lines.extend(render_applyable_receipts(applyable))
    if leftover:
        if locations or attached or deferred or skipped or applyable:
            lines.append("")
        lines.append(
            "These comments still have a suggested-diff fence that GitHub cannot apply:"
        )
        lines.append("")
        lines.extend(render_leftover_diff_receipts(leftover))
    lines.append("")
    return "\n".join(lines)


def _trusted_location_subset(
    items: list[tuple[str, int]] | None,
    allowed: set[tuple[str, int]],
) -> list[tuple[str, int]]:
    """Return first-seen locations that remain in the trusted control set."""
    if not items:
        return []
    kept: list[tuple[str, int]] = []
    seen: set[tuple[str, int]] = set()
    for item in items:
        if item not in allowed or item in seen:
            continue
        seen.add(item)
        kept.append(item)
    return kept


def _trusted_range_subset(
    items: list[tuple[str, int, int]] | None,
    allowed: set[tuple[str, int]],
) -> list[tuple[str, int, int]]:
    """Return first-seen applyable ranges whose start is a trusted finding."""
    if not items:
        return []
    kept: list[tuple[str, int, int]] = []
    seen: set[tuple[str, int, int]] = set()
    for item in items:
        path, start, _end = item
        if (path, start) not in allowed or item in seen:
            continue
        seen.add(item)
        kept.append(item)
    return kept


def _trusted_receipt_subset(
    items: list[tuple[str, int, str]] | None,
    allowed: set[tuple[str, int]],
) -> list[tuple[str, int, str]]:
    """Return first-seen leftover receipts whose path:line is a trusted finding."""
    if not items:
        return []
    kept: list[tuple[str, int, str]] = []
    seen: set[tuple[str, int]] = set()
    for path, line, reason in items:
        if (
            (path, line) not in allowed
            or (path, line) in seen
            or reason not in LEFTOVER_DIFF_REASONS
        ):
            continue
        seen.add((path, line))
        kept.append((path, line, reason))
    return kept


def render_inline_comment_failure_body(
    body: str,
    control: dict[str, Any],
    *,
    error_text: str = "",
    refused_locations: list[tuple[str, int]] | None = None,
    refused_receipts: list[tuple[str, int, str]] | None = None,
    attached_locations: list[tuple[str, int]] | None = None,
    deferred_locations: list[tuple[str, int]] | None = None,
    skipped_locations: list[tuple[str, int]] | None = None,
    applyable_locations: list[tuple[str, int, int]] | None = None,
    leftover_locations: list[tuple[str, int, str]] | None = None,
    retry_limit: int | None = None,
) -> str:
    """Append the 422 fallback suffix to an existing REQUEST_CHANGES body."""
    error_phrase = github_publication_error_phrase(error_text) if error_text else ""
    allowed = set(trusted_finding_locations(control))
    attached = (
        _trusted_location_subset(attached_locations, allowed)
        if attached_locations is not None
        else []
    )
    deferred = (
        _trusted_location_subset(deferred_locations, allowed)
        if deferred_locations is not None
        else []
    )
    skipped = (
        _trusted_location_subset(skipped_locations, allowed)
        if skipped_locations is not None
        else []
    )
    applyable = (
        _trusted_range_subset(applyable_locations, allowed)
        if applyable_locations is not None
        else []
    )
    leftover = (
        _trusted_receipt_subset(leftover_locations, allowed)
        if leftover_locations is not None
        else []
    )
    phrases: dict[tuple[str, int], str] | None = None
    if refused_receipts is not None:
        locations = [
            (path, line)
            for path, line, _phrase in refused_receipts
            if (path, line) in allowed
        ]
        phrases = {
            (path, line): phrase
            for path, line, phrase in refused_receipts
            if phrase and (path, line) in allowed
        }
        mixed_success = True
        if (
            not locations
            and not attached
            and not deferred
            and not skipped
            and not applyable
            and not leftover
        ):
            return body.rstrip("\n") + "\n"
    elif (
        refused_locations is None
        and attached_locations is None
        and deferred_locations is None
        and skipped_locations is None
        and applyable_locations is None
        and leftover_locations is None
    ):
        locations = trusted_finding_locations(control)
        mixed_success = False
    elif refused_locations is None:
        locations = []
        mixed_success = True
        if not attached and not deferred and not skipped and not applyable and not leftover:
            return body.rstrip("\n") + "\n"
    else:
        locations = [item for item in refused_locations if item in allowed]
        mixed_success = True
        if (
            not locations
            and not attached
            and not deferred
            and not skipped
            and not applyable
            and not leftover
        ):
            return body.rstrip("\n") + "\n"
    return body.rstrip("\n") + render_inline_comment_failure_suffix(
        locations,
        error_phrase=error_phrase,
        mixed_success=mixed_success,
        phrases=phrases,
        attached_locations=attached or None,
        deferred_locations=deferred or None,
        skipped_locations=skipped or None,
        applyable_locations=applyable or None,
        leftover_locations=leftover or None,
        retry_limit=retry_limit,
    )


def load_control(path: Path) -> dict[str, Any]:
    """Load one trusted review-control JSON object."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"control JSON could not be read: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("control JSON must be an object")
    return value


def main(argv: list[str] | None = None) -> int:
    """Write 422 fallback text or split a batch review into single comments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--control", type=Path)
    parser.add_argument("--body", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--error-file", type=Path)
    parser.add_argument("--split-payload", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--is-unprocessable", action="store_true")
    parser.add_argument("--refused-locations", type=Path)
    parser.add_argument("--attached-locations", type=Path)
    parser.add_argument("--deferred-locations", type=Path)
    parser.add_argument("--skipped-locations", type=Path)
    parser.add_argument("--applyable-locations", type=Path)
    parser.add_argument("--leftover-diff-locations", type=Path)
    parser.add_argument("--retry-limit", type=int)
    parser.add_argument("--record-refusal", action="store_true")
    parser.add_argument("--record-attach", action="store_true")
    parser.add_argument("--comment-file", type=Path)
    parser.add_argument("--filter-hunks", action="store_true")
    parser.add_argument("--payload", type=Path)
    parser.add_argument("--hunks-diff", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.filter_hunks:
            if args.payload is None or args.hunks_diff is None or args.output is None:
                raise ValueError(
                    "--payload, --hunks-diff, and --output are required "
                    "with --filter-hunks"
                )
            payload = load_control(args.payload)
            hunks = parse_unified_diff_hunk_lines(
                args.hunks_diff.read_text(encoding="utf-8")
            )
            write_hunk_filtered_payload(
                payload,
                hunks,
                args.output,
                skipped_path=args.skipped_locations,
                applyable_path=args.applyable_locations,
                leftover_path=args.leftover_diff_locations,
            )
            return 0
        if args.record_attach:
            if args.attached_locations is None or args.comment_file is None:
                raise ValueError(
                    "--attached-locations and --comment-file are required "
                    "with --record-attach"
                )
            payload = load_control(args.comment_file)
            comments = payload.get("comments")
            if (
                not isinstance(comments, list)
                or not comments
                or not isinstance(comments[0], dict)
            ):
                raise ValueError("comment file must contain comments[0]")
            first = comments[0]
            line = first.get("line")
            record_attached_receipt(
                args.attached_locations,
                str(first.get("path") or ""),
                line if isinstance(line, int) and not isinstance(line, bool) else 0,
            )
            return 0
        if args.record_refusal:
            if (
                args.refused_locations is None
                or args.comment_file is None
                or args.error_file is None
            ):
                raise ValueError(
                    "--refused-locations, --comment-file, and --error-file "
                    "are required with --record-refusal"
                )
            payload = load_control(args.comment_file)
            comments = payload.get("comments")
            if (
                not isinstance(comments, list)
                or not comments
                or not isinstance(comments[0], dict)
            ):
                raise ValueError("comment file must contain comments[0]")
            first = comments[0]
            line = first.get("line")
            record_refused_receipt(
                args.refused_locations,
                str(first.get("path") or ""),
                line if isinstance(line, int) and not isinstance(line, bool) else 0,
                args.error_file.read_text(encoding="utf-8"),
            )
            return 0
        if args.is_unprocessable:
            if args.error_file is None:
                raise ValueError("--error-file is required with --is-unprocessable")
            error_text = args.error_file.read_text(encoding="utf-8")
            return 0 if github_error_is_unprocessable(error_text) else 1
        if args.split_payload is not None:
            if args.output_dir is None:
                raise ValueError("--output-dir is required with --split-payload")
            payload = load_control(args.split_payload)
            write_single_comment_payloads(
                payload,
                args.output_dir,
                limit=args.retry_limit,
                deferred_path=args.deferred_locations,
            )
            return 0
        if args.control is None or args.body is None or args.output is None:
            raise ValueError("--control, --body, and --output are required")
        control = load_control(args.control)
        body = args.body.read_text(encoding="utf-8")
        error_text = (
            args.error_file.read_text(encoding="utf-8") if args.error_file else ""
        )
        refused_locations = None
        refused_receipts = None
        attached_locations = None
        deferred_locations = None
        skipped_locations = None
        applyable_locations = None
        leftover_locations = None
        if args.refused_locations is not None:
            parsed_receipts = parse_refused_receipts(
                args.refused_locations.read_text(encoding="utf-8")
            )
            if any(phrase for _path, _line, phrase in parsed_receipts):
                refused_receipts = parsed_receipts
            else:
                refused_locations = [
                    (path, line) for path, line, _phrase in parsed_receipts
                ]
        if args.attached_locations is not None:
            attached_locations = parse_refused_locations(
                args.attached_locations.read_text(encoding="utf-8")
            )
        if args.deferred_locations is not None:
            deferred_locations = parse_refused_locations(
                args.deferred_locations.read_text(encoding="utf-8")
            )
        if args.skipped_locations is not None:
            skipped_locations = parse_refused_locations(
                args.skipped_locations.read_text(encoding="utf-8")
            )
        if args.applyable_locations is not None:
            applyable_locations = parse_applyable_ranges(
                args.applyable_locations.read_text(encoding="utf-8")
            )
        if args.leftover_diff_locations is not None:
            leftover_locations = parse_leftover_diff_receipts(
                args.leftover_diff_locations.read_text(encoding="utf-8")
            )
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return 2
    args.output.write_text(
        render_inline_comment_failure_body(
            body,
            control,
            error_text=error_text,
            refused_locations=refused_locations,
            refused_receipts=refused_receipts,
            attached_locations=attached_locations,
            deferred_locations=deferred_locations,
            skipped_locations=skipped_locations,
            applyable_locations=applyable_locations,
            leftover_locations=leftover_locations,
            retry_limit=args.retry_limit,
        ),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through runpy CLI test
    raise SystemExit(main())
