#!/usr/bin/env python3
"""Refresh the section-4 open-PR inventory snapshot in the central gap baseline.

`docs/product-technical-gap-baseline.md` carries one SHA-bound row per open
`ContextualWisdomLab/.github` pull request. That table is a completeness
snapshot, never merge authorization, and it went stale every few days while it
was transcribed by hand. This regenerates the header count and the whole
section-4 table from `gh pr list` output in one command, keeping the shape the
baseline contract test (`tests/test_product_technical_gap_baseline.py`) pins:
`| #<n> |` rows, a 40-hex head SHA per row, and a declared count that matches.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import subprocess
import sys

REPO = "ContextualWisdomLab/.github"
BASELINE_PATH = Path("docs/product-technical-gap-baseline.md")
SECTION_HEADING = "## 4. 열린 PR live inventory"
GH_FIELDS = "number,title,headRefOid,baseRefName,mergeStateStatus,isDraft,reviewDecision"
ALLOWED_STATES = (
    "MERGEABLE",
    "CONFLICTING",
    "BLOCKED",
    "BEHIND",
    "DIRTY",
    "UNSTABLE",
    "CLEAN",
)
_KST = timezone(timedelta(hours=9), name="KST")


def fetch_open_prs(repo: str = REPO, attempts: int = 5) -> list[dict]:
    """Return open PRs as `gh pr list --json` dicts, retrying transient 5xx bodies."""
    command = [
        "gh",
        "pr",
        "list",
        "--repo",
        repo,
        "--state",
        "open",
        "--limit",
        "500",
        "--json",
        GH_FIELDS,
    ]
    detail = ""
    for _ in range(max(1, attempts)):
        done = subprocess.run(command, capture_output=True, text=True, check=False)
        payload = done.stdout.strip()
        if payload.startswith("["):
            return json.loads(payload)
        detail = done.stderr.strip()
    raise RuntimeError(f"gh pr list returned no JSON in {attempts} tries: {detail}")


def render_row(pull_request: dict) -> str:
    """Render one contract-conformant `| #<n> | ... |` inventory row."""
    merge_state = pull_request["mergeStateStatus"] or ""
    if merge_state not in ALLOWED_STATES:
        raise ValueError(
            f"PR #{pull_request['number']}: unmappable mergeStateStatus {merge_state!r}"
        )
    title = " ".join((pull_request["title"] or "").split()).replace("|", "/")
    review = pull_request["reviewDecision"] or "REVIEW_REQUIRED"
    mode = "draft" if pull_request["isDraft"] else "ready"
    return (
        f"| #{pull_request['number']} | {title} | `{pull_request['headRefOid']}` | "
        f"`{pull_request['baseRefName']}` | {merge_state} | {review} | {mode} |"
    )


def render_section(pull_requests: list[dict], stamp: str) -> str:
    """Return replacement text for section 4 (heading through the rendered table)."""
    ordered = sorted(pull_requests, key=lambda pull_request: pull_request["number"], reverse=True)
    rows = [render_row(pull_request) for pull_request in ordered]
    tally = {state: 0 for state in ALLOWED_STATES}
    draft_count = 0
    for pull_request in ordered:
        tally[pull_request["mergeStateStatus"]] += 1
        draft_count += 1 if pull_request["isDraft"] else 0
    summary = "; ".join(
        [f"total {len(ordered)}"]
        + [f"{state}={tally[state]}" for state in ALLOWED_STATES if tally[state]]
        + [f"draft={draft_count}"]
    )
    return "\n".join(
        [
            SECTION_HEADING,
            "",
            f"아래는 `gh pr list`가 {stamp}에 반환한 {len(ordered)}개 열린 PR의 "
            "number/title/exact head/base/metadata/review 상태다. 이 표는 관측 스냅샷이며, "
            "각 PR의 exact head에서 required Checks·unresolved thread·독립 승인·merge-result "
            "tree를 다시 확인하기 전에는 병합 판단에 쓰지 않는다.",
            "",
            f"스냅샷 요약: {summary}",
            "",
            "| PR | title | exact head SHA | base | metadata | review | mode |",
            "|---|---|---|---|---|---|---|",
            *rows,
        ]
    )


def splice(doc: str, section_text: str, count: int) -> str:
    """Replace the header PR count and the whole of section 4 in `doc`."""
    doc, changed = re.subn(
        r"(현재 열린 PR 수:\s*\*\*)\d+(\*\*)", rf"\g<1>{count}\g<2>", doc, count=1
    )
    if not changed:
        raise ValueError("gap baseline header 'PR count' line not found")
    start = doc.index(SECTION_HEADING)
    following_heading = doc.index("\n## ", start + len(SECTION_HEADING))
    return doc[:start] + section_text + "\n\n" + doc[following_heading + 1 :]


def main(argv: list[str]) -> int:
    """Refresh the gap-baseline inventory file named by `argv[0]`, in place."""
    path = Path(argv[0])
    pull_requests = fetch_open_prs()
    stamp = datetime.now(_KST).strftime("%Y-%m-%d %H:%M KST")
    updated = splice(
        path.read_text(encoding="utf-8"),
        render_section(pull_requests, stamp),
        len(pull_requests),
    )
    path.write_text(updated, encoding="utf-8")
    print(f"refreshed {path}: {len(pull_requests)} open PRs @ {stamp}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:] or [str(BASELINE_PATH)]))
