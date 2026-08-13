#!/usr/bin/env python3
"""Render a GitHub 422 inline-comment fallback that cites trusted path:line."""

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
HTTP_422_LINE_RE = re.compile(r"(?im)^(?:gh:\s*)?(.*HTTP 422.*)$")
SEALED_422_RE = re.compile(
    r"(?i)(?:HTTP\s+422|status(?:\s+code)?\s+422|Error code:\s*422|Unprocessable Entity)"
)


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
    index_by_location: dict[tuple[str, int], int] = {}
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
        own_phrase = phrase.strip()
        existing = index_by_location.get(location)
        if existing is None:
            index_by_location[location] = len(receipts)
            receipts.append((path, line_number, own_phrase))
            continue
        # Keep this comment's own 422 phrase when a later retry rewrites
        # the same path:line instead of dropping it as a duplicate row.
        receipts[existing] = (path, line_number, own_phrase)
    return receipts


def parse_refused_locations(text: str) -> list[tuple[str, int]]:
    """Parse ``path:line`` rows from one-at-a-time retry failures."""
    return [(path, line) for path, line, _phrase in parse_refused_receipts(text)]


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


def _collapse_error_text(text: str) -> str:
    """Return one-line error text without URLs or extra whitespace."""
    without_urls = re.sub(r"https?://\S+", "", text)
    return " ".join(without_urls.split())


def escape_receipt_text(text: str) -> str:
    """Escape HTML and Markdown metacharacters in a receipt phrase."""
    escaped = text
    for character, replacement in (
        ("`", "\\u0060"),
        ("<", "\\u003c"),
        (">", "\\u003e"),
        ("&", "\\u0026"),
    ):
        escaped = escaped.replace(character, replacement)
    return escaped


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
        phrase = f"GitHub HTTP 422: {'; '.join(messages)}"
    else:
        match = HTTP_422_LINE_RE.search(raw)
        if match:
            line = _collapse_error_text(match.group(1))
            if line.casefold().startswith("github http 422"):
                phrase = line
            else:
                phrase = f"GitHub HTTP 422: {line}".rstrip(": ")
        elif SEALED_422_RE.search(raw):
            phrase = "GitHub HTTP 422"
        else:
            phrase = "GitHub review write failed"
    return escape_receipt_text(phrase[:ERROR_PHRASE_MAX_CHARS])


def github_error_is_unprocessable(text: str) -> bool:
    """Return whether GitHub rejected the review write as HTTP 422."""
    raw = text or ""
    if SEALED_422_RE.search(raw):
        return True
    return SEALED_422_RE.search(github_publication_error_phrase(raw)) is not None


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



def sanitize_leftover_excerpt(text: str) -> str:
    """Return leftover receipt text that cannot break the overview HTML comment.

    Leftover ``path:line`` rows live in ``<!-- opencode-review-overview -->``.
    A leftover path or reason with ``-->`` or an HTML metacharacter would
    close that comment or inject markup (CWE-116). Fence markers are also
    removed so a leftover cannot reopen a GitHub suggestion block.
    """
    excerpt = (text or "").replace("\r\n", "\n").replace("\t", " ")
    excerpt = (
        excerpt.replace("```", "")
        .replace("<!--", "")
        .replace("-->", "")
        .replace("<", "")
        .replace(">", "")
        .replace("&", "")
    )
    return excerpt.strip("\n")


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
        path = sanitize_leftover_excerpt(path)
        if phrase:
            lines.append(f"- `{path}:{line}` — {escape_receipt_text(phrase)}")
        else:
            lines.append(f"- `{path}:{line}`")
    return lines


def render_inline_comment_failure_suffix(
    locations: list[tuple[str, int]],
    *,
    error_phrase: str = "",
    mixed_success: bool = False,
    phrases: dict[tuple[str, int], str] | None = None,
) -> str:
    """Return the PR-body suffix used when GitHub rejects inline comments."""
    heading = (
        "## Inline comment publication receipts"
        if error_phrase or mixed_success
        else "## Inline comment publishing failed"
    )
    lines = [
        "",
        heading,
        "",
    ]
    if locations:
        if mixed_success:
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
    else:
        lines.append(
            "GitHub did not accept the inline review comments, and the "
            "control JSON had no trusted path:line findings. Inspect the "
            "workflow log and apply any remaining blockers from the review "
            "body manually."
        )
        if error_phrase:
            lines.append("")
            lines.append(f"- GitHub error: {escape_receipt_text(error_phrase)}")
    lines.append("")
    return "\n".join(lines)


def render_inline_comment_failure_body(
    body: str,
    control: dict[str, Any],
    *,
    error_text: str = "",
    refused_locations: list[tuple[str, int]] | None = None,
    refused_receipts: list[tuple[str, int, str]] | None = None,
) -> str:
    """Append the 422 fallback suffix to an existing REQUEST_CHANGES body."""
    error_phrase = github_publication_error_phrase(error_text) if error_text else ""
    phrases: dict[tuple[str, int], str] | None = None
    if refused_receipts is not None:
        allowed = set(trusted_finding_locations(control))
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
        if not locations:
            return body.rstrip("\n") + "\n"
    elif refused_locations is None:
        locations = trusted_finding_locations(control)
        mixed_success = False
    else:
        allowed = set(trusted_finding_locations(control))
        locations = [item for item in refused_locations if item in allowed]
        mixed_success = True
        if not locations:
            return body.rstrip("\n") + "\n"
    return body.rstrip("\n") + render_inline_comment_failure_suffix(
        locations,
        error_phrase=error_phrase,
        mixed_success=mixed_success,
        phrases=phrases,
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
    parser.add_argument("--retry-limit", type=int)
    parser.add_argument("--deferred-locations", type=Path)
    parser.add_argument("--is-unprocessable", action="store_true")
    parser.add_argument("--refused-locations", type=Path)
    parser.add_argument("--record-refusal", action="store_true")
    parser.add_argument("--comment-file", type=Path)
    args = parser.parse_args(argv)
    try:
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
        ),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through runpy CLI test
    raise SystemExit(main())
