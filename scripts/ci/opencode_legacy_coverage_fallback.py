"""Recognize only the complete historical coverage-failure publisher envelope.

This is refresh evidence, never approval or merge authority. Unknown content,
including unrecognized diagrams, remains a substantive review blocker.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

try:
    from scripts.ci.opencode_review_surfaces import build_fallback_review, emit_mermaid
except ModuleNotFoundError:
    from opencode_review_surfaces import build_fallback_review, emit_mermaid


_PATH_ROW = re.compile(r"- `([A-Za-z0-9_.@+/-]{1,512})` — [^\n]+")
_IDENTITY = re.compile(
    r"- Head SHA: `([0-9a-fA-F]{40})`\n"
    r"- Workflow run: ([1-9][0-9]{0,19})\n"
    r"- Workflow attempt: ([1-9][0-9]{0,19})\n"
    r"- Coverage gate: `failure`\n"
)
_OUTCOME = (
    "\n## Review outcome\n\n"
    "Coverage is a gate, not the review. This body reviews the changed product files."
)


def is_legacy_coverage_only_review(review: Mapping[str, Any], head_sha: str) -> bool:
    """Validate identity and reconstruct the entire bounded producer body exactly."""
    author = review.get("user") or review.get("author") or {}
    commit = review.get("commit") or {}
    commit_sha = review.get("commit_id") or (
        commit.get("oid") or commit.get("sha") if isinstance(commit, Mapping) else ""
    )
    if (
        not isinstance(author, Mapping)
        or author.get("login") not in {"opencode-agent", "opencode-agent[bot]"}
        or review.get("state") not in {"CHANGES_REQUESTED", "APPROVED", "COMMENTED"}
        or not re.fullmatch(r"[0-9a-fA-F]{40}", head_sha)
        or str(commit_sha).lower() != head_sha.lower()
    ):
        return False
    body = str(review.get("body") or "")
    identities = list(_IDENTITY.finditer(body))
    if len(identities) != 1 or identities[0].group(1).lower() != head_sha.lower():
        return False
    identity = identities[0]
    paths = [match.group(1) for match in _PATH_ROW.finditer(body)]
    if (
        not paths
        or len(paths) > 200
        or any(
            path.startswith("/")
            or any(part in {"", ".", ".."} for part in path.split("/"))
            for path in paths
        )
    ):
        return False
    try:
        expected = (
            build_fallback_review(
                changed_files=paths,
                head_sha=identity.group(1),
                run_id=identity.group(2),
                run_attempt=identity.group(3),
                coverage_result="failure",
            )
            + _OUTCOME
        )
    except ValueError:
        return False
    # The publisher always appended the evidence map. Its graph is reconstructed
    # from paths, not accepted as arbitrary Mermaid text that could hide findings.
    for merge_state in ("UNKNOWN", "DIRTY"):
        candidate = (
            expected
            + "\n\n## Changed-File Evidence Map\n\n"
            + emit_mermaid(paths, merge_state=merge_state).rstrip("\n")
        )
        if body == candidate or body == candidate + "\n":
            return True
    return False
