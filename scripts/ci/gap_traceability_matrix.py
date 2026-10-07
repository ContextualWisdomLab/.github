#!/usr/bin/env python3
"""Build a Gap-to-work traceability matrix from the Gap register and GitHub inventories.

``docs/product-technical-gap-baseline.md`` requires new work to link its Gap ID
in the PR description. This offline, standard-library-only tool measures that
requirement. It reads the register and inventories exported with::

    gh pr list --state open --limit 1000 --json number,title,body,isDraft,url
    gh issue list --state open --limit 1000 --json number,title,body,url

It then writes a JSON and Markdown matrix. For each register ID the matrix lists
the PRs and issues that mention it. It also lists register IDs without work,
work without any known ID, references to IDs absent from the register
(dangling), and duplicate register IDs.

A mention is a textual reference, not proof that the work implements the gap.
The ``--require-link`` modes only check that a PR names at least one ID that
the register defines.

Exit codes:
    0  report written, or the checked PR links to a known register ID
    1  the checked PR links to no known register ID
    2  invalid arguments or input: unreadable file, malformed JSON, empty
       register, unwritable output, or a ``--require-link`` PR absent from
       the inventory
    3  duplicate register IDs exist and ``--fail-on-duplicates`` is set;
       this is checked before any link check
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

SCHEMA_VERSION = "cwl.gap-traceability-matrix/1"
DESCRIPTION_LIMIT = 160

EXIT_OK = 0
EXIT_UNLINKED = 1
EXIT_INPUT = 2
EXIT_DUPLICATE = 3

_ID_CORE = r"(?:G|PRD|TRD|CONTROL)(?:-[A-Z][A-Z0-9]*)*-\d{2,3}"
# A slash may separate two IDs (G-04/G-09) but not follow a path segment.
_LEFT = r"(?<![A-Za-z0-9_\-])(?<!(?<![0-9])/)(?<![A-Za-z0-9]\.)"
_RIGHT = r"(?![A-Za-z0-9_\-])"
ID_PATTERN = re.compile(_LEFT + "(" + _ID_CORE + ")" + _RIGHT)
FULL_ID_PATTERN = re.compile(r"\A" + _ID_CORE + r"\Z")

FENCE_LINE_PATTERN = re.compile(r"^[ \\t]{0,3}((?:`{3,})|(?:~{3,}))(.*)$")
INLINE_CODE_RUN_PATTERN = re.compile(r"`+")
# Every pattern below must stay linear on hostile PR bodies: unclosed
# comments run to the end, link targets cannot restart inside themselves and
# URL schemes are bounded so a long hyphenated token cannot backtrack.
LINK_TARGET_PATTERN = re.compile(r"\]\([^()\s]*(?:\s[^()]*)?\)")
URL_PATTERN = re.compile(r"\b[a-z][a-z0-9+.\-]{0,31}://[^\s<>()\[\]]+", re.I)

REGISTER_HEADERS = frozenset({"gap id", "id"})


class InputError(ValueError):
    """Raised when an input file is unreadable or has the wrong shape."""


@dataclass(frozen=True)
class GapEntry:
    """One register row: an ID, its short description and its source line."""

    gap_id: str
    description: str
    line: int


@dataclass(frozen=True)
class WorkItem:
    """A PR or issue and the Gap IDs its title and body mention."""

    kind: str
    number: int
    title: str
    url: str
    is_draft: bool
    mentions: frozenset[str]


def split_cells(row: str) -> list[str]:
    """Split a Markdown table row on unescaped pipes and strip each cell."""
    body = row.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|") and not body.endswith("\\|"):
        body = body[:-1]
    return [cell.strip() for cell in re.split(r"(?<!\\)\|", body)]


def clean_cell(cell: str) -> str:
    """Remove emphasis, code and link markup from a table cell."""
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", cell)
    text = text.replace("**", "").replace("`", "").replace("\\|", "|")
    return re.sub(r"\s+", " ", text).strip()


def shorten(text: str, limit: int = DESCRIPTION_LIMIT) -> str:
    """Cut ``text`` to ``limit`` characters, marking a cut with an ellipsis."""
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _fence_parts(line: str) -> tuple[str, int, str] | None:
    """Return a fence character, run length and trailing text for a fence line."""
    match = FENCE_LINE_PATTERN.match(line)
    if not match:
        return None
    marker, trailing = match.groups()
    return marker[0], len(marker), trailing


def _fence_opener(line: str) -> tuple[str, int] | None:
    """Return a valid CommonMark-style opener, rejecting backticks in its info."""
    parts = _fence_parts(line)
    if not parts:
        return None
    character, length, trailing = parts
    if character == "`" and "`" in trailing:
        return None
    return character, length


def _closes_fence(line: str, fence: tuple[str, int]) -> bool:
    """Return whether ``line`` is a same-character, long-enough clean closer."""
    parts = _fence_parts(line)
    return bool(
        parts
        and parts[0] == fence[0]
        and parts[1] >= fence[1]
        and not parts[2].strip()
    )


def _strip_fenced_blocks(text: str) -> str:
    """Remove fenced blocks while preserving line boundaries for later scans."""
    output: list[str] = []
    fence: tuple[str, int] | None = None
    for line in text.splitlines(keepends=True):
        raw = line.rstrip("\\r\\n")
        ending = line[len(raw) :]
        if fence:
            if _closes_fence(raw, fence):
                fence = None
            output.append(ending or " ")
            continue
        opener = _fence_opener(raw)
        if opener:
            fence = opener
            output.append(ending or " ")
        else:
            output.append(line)
    return "".join(output)


def _strip_html_comments(text: str) -> str:
    """Remove HTML comments in one forward scan; an unclosed comment runs to EOF."""
    output: list[str] = []
    cursor = 0
    while True:
        start = text.find("<!--", cursor)
        if start < 0:
            output.append(text[cursor:])
            break
        output.append(text[cursor:start])
        output.append(" ")
        end = text.find("-->", start + 4)
        if end < 0:
            break
        cursor = end + 3
    return "".join(output)


def _strip_inline_code(text: str) -> str:
    """Remove code spans of any backtick-run length, keeping exact Gap IDs."""
    output: list[str] = []
    for line in text.splitlines(keepends=True):
        runs = list(INLINE_CODE_RUN_PATTERN.finditer(line))
        cursor = 0
        run_index = 0
        while run_index < len(runs):
            opener = runs[run_index]
            closer_index = run_index + 1
            while (
                closer_index < len(runs)
                and len(runs[closer_index].group()) != len(opener.group())
            ):
                closer_index += 1
            if closer_index == len(runs):
                run_index += 1
                continue
            closer = runs[closer_index]
            output.append(line[cursor : opener.start()])
            code_content = line[opener.end() : closer.start()].strip()
            output.append(
                f" {code_content} " if FULL_ID_PATTERN.match(code_content) else " "
            )
            cursor = closer.end()
            run_index = closer_index + 1
        output.append(line[cursor:])
    return "".join(output)


def _is_table_separator(cells: list[str]) -> bool:
    """Return whether every cell is a Markdown table delimiter cell."""
    return bool(cells) and all(
        re.fullmatch(r":?-{3,}:?", clean_cell(cell)) for cell in cells
    )


def parse_register(markdown: str) -> list[GapEntry]:
    """Return every register row in document order, duplicates included.

    A register row is a body row of a Markdown table whose header's first cell
    is ``Gap ID`` or ``ID`` and whose first cell is exactly one Gap ID. IDs in
    other cells, other tables, fenced code or prose are not definitions.
    """
    entries: list[GapEntry] = []
    in_register = False
    awaiting_separator = False
    previous_was_table = False
    fence: tuple[str, int] | None = None
    for index, raw in enumerate(markdown.splitlines(), start=1):
        if fence:
            if _closes_fence(raw, fence):
                fence = None
            continue
        opener = _fence_opener(raw)
        if opener:
            fence = opener
            in_register = False
            awaiting_separator = False
            previous_was_table = False
            continue
        line = raw.strip()
        if not line.startswith("|"):
            in_register = False
            awaiting_separator = False
            previous_was_table = False
            continue
        cells = split_cells(line)
        if not previous_was_table:
            awaiting_separator = clean_cell(cells[0]).lower() in REGISTER_HEADERS
            in_register = False
            previous_was_table = True
            continue
        previous_was_table = True
        if awaiting_separator:
            in_register = _is_table_separator(cells)
            awaiting_separator = False
            continue
        if not in_register:
            continue
        candidate = clean_cell(cells[0])
        if FULL_ID_PATTERN.match(candidate):
            description = clean_cell(cells[1]) if len(cells) > 1 else ""
            entries.append(GapEntry(candidate, shorten(description), index))
    return entries


def mention_text(text: str) -> str:
    """Remove text regions that must not produce mentions.

    Fenced blocks, HTML comments, URLs and link targets are removed. Inline
    code is removed unless it contains exactly one Gap ID, because PR bodies
    in this organization routinely quote IDs as code. Link text is kept.
    """
    text = text.replace("\\r\\n", "\\n")
    text = _strip_fenced_blocks(text)
    text = _strip_html_comments(text)
    text = _strip_inline_code(text)
    text = LINK_TARGET_PATTERN.sub("]", text)
    return URL_PATTERN.sub(" ", text)


def extract_mentions(text: str) -> frozenset[str]:
    """Return the Gap IDs that ``text`` mentions.

    Range notation such as ``G-01..G-16`` yields only its two endpoints. PR
    bodies use ranges both for "these gaps" and for "outside these gaps", so
    expanding them would create links that the author did not claim.
    """
    return frozenset(match.group(1) for match in ID_PATTERN.finditer(mention_text(text)))


def load_json_list(path: Path, label: str) -> list[dict[str, Any]]:
    """Load a JSON array of objects from ``path`` or raise ``InputError``."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InputError(f"{label}: cannot read JSON from {path}: {exc}") from exc
    if not isinstance(data, list) or not all(isinstance(row, dict) for row in data):
        raise InputError(f"{label}: expected a JSON array of objects in {path}")
    return data


def parse_work_items(rows: Iterable[dict[str, Any]], kind: str) -> list[WorkItem]:
    """Convert ``gh --json`` rows into work items with their Gap mentions."""
    items: list[WorkItem] = []
    for row in rows:
        number = row.get("number")
        if isinstance(number, bool) or not isinstance(number, int) or number <= 0:
            raise InputError(f"{kind}: every row needs a positive integer 'number'")
        title = row.get("title") or ""
        body = row.get("body") or ""
        if not isinstance(title, str) or not isinstance(body, str):
            raise InputError(f"{kind} #{number}: 'title' and 'body' must be strings")
        items.append(
            WorkItem(
                kind=kind,
                number=number,
                title=title,
                url=str(row.get("url") or ""),
                is_draft=row.get("isDraft") is True,
                mentions=extract_mentions(title + "\n" + body),
            )
        )
    return items


def _ref(item: WorkItem) -> dict[str, Any]:
    """Return the compact JSON reference for a work item."""
    return {
        "number": item.number,
        "title": item.title,
        "url": item.url,
        "is_draft": item.is_draft,
    }


def build_matrix(
    entries: Sequence[GapEntry],
    work: Sequence[WorkItem],
    inputs: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build the deterministic traceability matrix as a JSON-ready dict."""
    first: dict[str, GapEntry] = {}
    duplicate_lines: dict[str, list[int]] = {}
    for entry in entries:
        if entry.gap_id in first:
            duplicate_lines.setdefault(entry.gap_id, [first[entry.gap_id].line])
            duplicate_lines[entry.gap_id].append(entry.line)
        else:
            first[entry.gap_id] = entry
    known = set(first)
    ordered = sorted(work, key=lambda item: (item.kind, item.number))
    gaps: dict[str, Any] = {}
    for gap_id, entry in first.items():
        linked = [item for item in ordered if gap_id in item.mentions]
        gaps[gap_id] = {
            "description": entry.description,
            "line": entry.line,
            "prs": [_ref(item) for item in linked if item.kind == "pr"],
            "issues": [_ref(item) for item in linked if item.kind == "issue"],
        }
    dangling: dict[str, list[dict[str, Any]]] = {}
    for item in ordered:
        for gap_id in sorted(item.mentions - known):
            dangling.setdefault(gap_id, []).append({"kind": item.kind, **_ref(item)})
    unlinked_work = [
        {"kind": item.kind, **_ref(item)}
        for item in ordered
        if not item.mentions & known
    ]
    unlinked_gaps = [
        gap_id for gap_id, row in gaps.items() if not row["prs"] and not row["issues"]
    ]
    linked_count = len(ordered) - len(unlinked_work)
    return {
        "schema_version": SCHEMA_VERSION,
        "inputs": dict(sorted((inputs or {}).items())),
        "summary": {
            "register_ids": len(first),
            "register_rows": len(entries),
            "work_items": len(ordered),
            "prs": sum(1 for item in ordered if item.kind == "pr"),
            "issues": sum(1 for item in ordered if item.kind == "issue"),
            "linked_work_items": linked_count,
            "unlinked_work_items": len(unlinked_work),
            "unlinked_gaps": len(unlinked_gaps),
            "dangling_ids": len(dangling),
            "duplicate_register_ids": len(duplicate_lines),
        },
        "gaps": gaps,
        "unlinked_gaps": unlinked_gaps,
        "unlinked_work": unlinked_work,
        "dangling_references": dict(sorted(dangling.items())),
        "duplicate_register_ids": dict(sorted(duplicate_lines.items())),
    }


def _md(text: str) -> str:
    """Escape a value for one Markdown table cell."""
    return text.replace("|", "\\|").replace("\n", " ")


def _numbers(refs: Sequence[dict[str, Any]]) -> str:
    """Render work references as ``#N`` numbers, marking drafts."""
    if not refs:
        return "—"
    return ", ".join(
        f"#{ref['number']}" + (" (draft)" if ref.get("is_draft") else "") for ref in refs
    )


def render_markdown(matrix: dict[str, Any], generated_at: str) -> str:
    """Render the matrix as a human-readable Markdown report."""
    summary = matrix["summary"]
    lines = [
        "# Gap traceability matrix",
        "",
        f"Generated: {generated_at}. Schema: `{matrix['schema_version']}`.",
        "",
        "A mention is a textual reference in a PR or issue title or body. It is",
        "not evidence that the work implements, verifies or closes the gap.",
        "",
        "## Summary",
        "",
        "| Measure | Count |",
        "| --- | --- |",
    ]
    lines += [f"| {key.replace('_', ' ')} | {value} |" for key, value in summary.items()]
    lines += ["", "## Register coverage", "", "| Gap ID | Description | PRs | Issues |"]
    lines.append("| --- | --- | --- | --- |")
    for gap_id, row in matrix["gaps"].items():
        lines.append(
            f"| {gap_id} | {_md(row['description'])} | {_numbers(row['prs'])} | "
            f"{_numbers(row['issues'])} |"
        )
    lines += ["", "## Dangling references", ""]
    if matrix["dangling_references"]:
        lines += ["| Referenced ID | Work items |", "| --- | --- |"]
        for gap_id, refs in matrix["dangling_references"].items():
            lines.append(f"| {gap_id} | {_numbers(refs)} |")
    else:
        lines.append("None.")
    lines += ["", "## Duplicate register IDs", ""]
    if matrix["duplicate_register_ids"]:
        for gap_id, line_numbers in matrix["duplicate_register_ids"].items():
            lines.append(f"- {gap_id}: lines {', '.join(map(str, line_numbers))}")
    else:
        lines.append("None.")
    lines += ["", "## Work without a known Gap ID", ""]
    lines.append(f"{summary['unlinked_work_items']} items. See the JSON report for the list.")
    return "\n".join(lines) + "\n"


def require_link(
    known_ids: set[str], items: Sequence[WorkItem], number: int
) -> tuple[int, str]:
    """Check that PR ``number`` mentions a known register ID."""
    for item in items:
        if item.kind == "pr" and item.number == number:
            known = sorted(item.mentions & known_ids)
            if known:
                return EXIT_OK, f"PR #{number} links {', '.join(known)}"
            unknown = sorted(item.mentions - known_ids)
            detail = f" (unknown: {', '.join(unknown)})" if unknown else ""
            return EXIT_UNLINKED, f"PR #{number} links no known Gap ID{detail}"
    return EXIT_INPUT, f"PR #{number} is not in the PR inventory"


def pr_from_event(path: Path) -> WorkItem:
    """Read the PR from a ``pull_request`` or ``pull_request_target`` payload."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InputError(f"event: cannot read JSON from {path}: {exc}") from exc
    pull = payload.get("pull_request") if isinstance(payload, dict) else None
    if not isinstance(pull, dict):
        raise InputError("event: payload has no 'pull_request' object")
    row = {
        "number": pull.get("number"),
        "title": pull.get("title"),
        "body": pull.get("body"),
        "isDraft": pull.get("draft", False),
        "url": pull.get("html_url"),
    }
    return parse_work_items([row], "pr")[0]


def sha256_file(path: Path) -> str:
    """Return the SHA-256 hex digest of a file's bytes."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_text(path: Path, text: str) -> None:
    """Write a report file, converting OS errors into ``InputError``."""
    try:
        path.write_text(text, encoding="utf-8")
    except OSError as exc:
        raise InputError(f"output: cannot write {path}: {exc}") from exc


def build_arg_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    parser = argparse.ArgumentParser(
        description="Build a Gap-to-work traceability matrix."
    )
    parser.add_argument(
        "--register",
        type=Path,
        default=Path("docs/product-technical-gap-baseline.md"),
        help="Gap register Markdown file",
    )
    parser.add_argument("--prs", type=Path, help="gh pr list --json export")
    parser.add_argument("--issues", type=Path, help="gh issue list --json export")
    parser.add_argument("--output-json", type=Path, help="write the JSON matrix here")
    parser.add_argument("--output-md", type=Path, help="write the Markdown report here")
    parser.add_argument("--generated-at", default="unspecified", help="report timestamp label")
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--require-link", type=int, metavar="PR", help="check one PR from --prs"
    )
    group.add_argument(
        "--require-link-event",
        type=Path,
        metavar="EVENT_JSON",
        help="check the PR in a GitHub event payload (for example $GITHUB_EVENT_PATH)",
    )
    parser.add_argument(
        "--fail-on-duplicates",
        action="store_true",
        help="exit 3 when the register defines an ID more than once",
    )
    return parser


def run(args: argparse.Namespace) -> int:
    """Execute the parsed command and return its exit code."""
    try:
        markdown = args.register.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise InputError(f"register: cannot read {args.register}: {exc}") from exc
    entries = parse_register(markdown)
    if not entries:
        raise InputError(f"register: no Gap ID rows found in {args.register}")
    known_ids = {entry.gap_id for entry in entries}
    duplicates = len(entries) != len(known_ids)
    if duplicates:
        print("warning: duplicate register IDs found", file=sys.stderr)
        if args.fail_on_duplicates:
            return EXIT_DUPLICATE
    if args.require_link_event is not None:
        item = pr_from_event(args.require_link_event)
        code, message = require_link(known_ids, [item], item.number)
        print(message)
        return code
    work: list[WorkItem] = []
    inputs = {"register_sha256": sha256_file(args.register)}
    if args.prs is not None:
        work += parse_work_items(load_json_list(args.prs, "prs"), "pr")
        inputs["prs_sha256"] = sha256_file(args.prs)
    if args.issues is not None:
        work += parse_work_items(load_json_list(args.issues, "issues"), "issue")
        inputs["issues_sha256"] = sha256_file(args.issues)
    if args.require_link is not None:
        if args.prs is None:
            raise InputError("--require-link needs --prs")
        code, message = require_link(known_ids, work, args.require_link)
        print(message)
        return code
    matrix = build_matrix(entries, work, inputs)
    if args.output_json is not None:
        write_text(args.output_json, json.dumps(matrix, ensure_ascii=False, indent=2) + "\n")
    if args.output_md is not None:
        write_text(args.output_md, render_markdown(matrix, args.generated_at))
    print(json.dumps(matrix["summary"], ensure_ascii=False, sort_keys=True))
    return EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    """Command-line entry point. Input errors exit 2 with a message on stderr."""
    args = build_arg_parser().parse_args(argv)
    try:
        return run(args)
    except InputError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_INPUT


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
