#!/usr/bin/env python3
"""Compose evidence-gated GitHub issue drafts; create one only when explicitly told to.

This module is the first increment of ADR-0022
(``docs/adr/0022-agent-pr-followup-search-and-issue-authoring-scope.md``): issue authoring is more
consequential than PR comments or review-finding repair because it creates new public-visible
content, and ``docs/product-goal-directive.md`` — this organization's standing autonomous-loop
authorization — names PR handling explicitly but never mentions issue creation. Until that
directive text is extended (see ``.github#1682``), no workflow in this repository invokes this
module's ``--create`` path unattended.

Two safety properties hold regardless of caller:

1. ``load_draft``/``render_markdown_body`` are pure and never touch the network. A draft with no
   findings, no citations, or no traceable source is rejected outright (``IssueDraftError``),
   matching this organization's "no heuristics without justification" evidence standard.
2. ``main`` only calls ``gh api`` when the caller passes ``--create`` explicitly. The default mode
   (no flag) renders the draft to stdout and returns without any GitHub side effect, mirroring
   ``infra/cloudflare/reconcile.sh``'s dry-run-by-default convention for consequential writes.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import re
import sys
from pathlib import Path
from typing import Any, Sequence

try:
    from pr_review_merge_scheduler import run
except ModuleNotFoundError:  # pragma: no cover - import shape depends on caller cwd
    from scripts.ci.pr_review_merge_scheduler import run


REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
LABEL_RE = re.compile(r"^[A-Za-z0-9_.: -]{1,50}$")
MAX_TITLE_LENGTH = 256
GOVERNING_ADR = "docs/adr/0022-agent-pr-followup-search-and-issue-authoring-scope.md"
ATTRIBUTION_FOOTER = (
    "---\n"
    "Drafted by an evidence-gated composer (`scripts/ci/issue_draft_composer.py`); not opened "
    "automatically by any scheduled or dispatched workflow. A human (or an agent working "
    f"interactively) ran this tool with `--create` explicitly. See {GOVERNING_ADR}."
)


class IssueDraftError(ValueError):
    """Raised when evidence for a drafted issue is missing or malformed."""


@dataclasses.dataclass(frozen=True)
class Finding:
    """One evidence-backed observation supporting the drafted issue."""

    description: str
    citation: str


@dataclasses.dataclass(frozen=True)
class IssueDraft:
    """Structured, evidence-gated input for one drafted GitHub issue."""

    repo: str
    title: str
    summary: str
    findings: tuple[Finding, ...]
    source: str
    labels: tuple[str, ...] = ()


def _non_empty_str(value: Any, *, field: str) -> str:
    """Return ``value`` as a non-empty stripped string or raise ``IssueDraftError``."""
    if type(value) is not str or not value.strip():
        raise IssueDraftError(f"{field} must be a non-empty string")
    return value.strip()


def load_draft(payload: dict[str, Any]) -> IssueDraft:
    """Validate a raw evidence payload and return a structured, evidence-gated ``IssueDraft``.

    Rejects a draft with no findings, no citations, or no traceable source rather than silently
    accepting one, so a caller cannot compose (and, with ``--create``, publish) an unsupported
    issue by omission.
    """
    if type(payload) is not dict:
        raise IssueDraftError("evidence payload must be a JSON object")

    repo = _non_empty_str(payload.get("repo"), field="repo")
    if not REPOSITORY_RE.fullmatch(repo):
        raise IssueDraftError(f"repo must look like owner/repo, got {repo!r}")

    title = _non_empty_str(payload.get("title"), field="title")
    if len(title) > MAX_TITLE_LENGTH:
        raise IssueDraftError(f"title exceeds {MAX_TITLE_LENGTH} characters")

    summary = _non_empty_str(payload.get("summary"), field="summary")
    source = _non_empty_str(payload.get("source"), field="source")

    raw_findings = payload.get("findings")
    if type(raw_findings) is not list or not raw_findings:
        raise IssueDraftError("findings must be a non-empty array")
    findings: list[Finding] = []
    for index, raw in enumerate(raw_findings):
        if type(raw) is not dict:
            raise IssueDraftError(f"findings[{index}] must be an object")
        description = _non_empty_str(raw.get("description"), field=f"findings[{index}].description")
        citation = _non_empty_str(raw.get("citation"), field=f"findings[{index}].citation")
        findings.append(Finding(description=description, citation=citation))

    raw_labels = payload.get("labels", [])
    if type(raw_labels) is not list:
        raise IssueDraftError("labels must be an array")
    labels: list[str] = []
    for index, raw in enumerate(raw_labels):
        if type(raw) is not str or not LABEL_RE.fullmatch(raw):
            raise IssueDraftError(f"labels[{index}] is invalid")
        labels.append(raw)

    return IssueDraft(
        repo=repo,
        title=title,
        summary=summary,
        findings=tuple(findings),
        source=source,
        labels=tuple(labels),
    )


def render_markdown_body(draft: IssueDraft) -> str:
    """Render the drafted issue body as evidence-gated Markdown."""
    lines = ["## Summary", "", draft.summary, "", "## Evidence", ""]
    for finding in draft.findings:
        lines.append(f"- {finding.description} ({finding.citation})")
    lines.extend(["", "## Source", "", draft.source, "", ATTRIBUTION_FOOTER])
    return "\n".join(lines)


def render_draft_text(draft: IssueDraft) -> str:
    """Render the full human-reviewable draft: repo, title, labels, and body."""
    header = [f"Repo: {draft.repo}", f"Title: {draft.title}"]
    if draft.labels:
        header.append(f"Labels: {', '.join(draft.labels)}")
    return "\n".join(header) + "\n\n" + render_markdown_body(draft)


def create_issue(draft: IssueDraft) -> str:
    """Create the drafted issue via the GitHub REST API and return its URL.

    Only reached when a caller explicitly passes ``--create``; see the module docstring and
    ``ATTRIBUTION_FOOTER`` for the authorization boundary this preserves.
    """
    args = [
        "gh",
        "api",
        "-X",
        "POST",
        f"repos/{draft.repo}/issues",
        "-f",
        f"title={draft.title}",
        "-f",
        f"body={render_markdown_body(draft)}",
    ]
    for label in draft.labels:
        args.extend(["-f", f"labels[]={label}"])
    result = json.loads(run(args))
    return str(result.get("html_url") or "")


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--evidence-file",
        type=Path,
        required=True,
        help="Path to a JSON evidence payload (repo, title, summary, findings, source, labels).",
    )
    parser.add_argument(
        "--create",
        action="store_true",
        help="Actually create the issue via `gh api`. Default: render the draft only, no GitHub call.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint: draft-only by default, create only with ``--create``."""
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        payload = json.loads(args.evidence_file.read_text(encoding="utf-8"))
        draft = load_draft(payload)
    except (OSError, json.JSONDecodeError, IssueDraftError) as exc:
        print(f"issue_draft_composer: {exc}", file=sys.stderr)
        return 1

    if not args.create:
        print(render_draft_text(draft))
        return 0

    print(create_issue(draft))
    return 0


if __name__ == "__main__":
    sys.exit(main())
