"""One-shot source repair for ContextualWisdomLab/.github PR #1706.

This temporary driver performs exact-string, fail-closed mutations only.  The
workflow that invokes it removes this file after the permanent regression has
passed, so the production tree retains only the reviewed workflow/test/docs
delta.
"""

from __future__ import annotations

from pathlib import Path


SCHEDULER = Path(".github/workflows/pr-review-merge-scheduler.yml")
OPENCODE = Path(".github/workflows/opencode-review.yml")
TEST = Path("tests/test_opencode_required_verdict_reconciliation_contract.py")
BASELINE = Path("docs/product-technical-gap-baseline.md")


OLD_FILTER = '''                | select(.state == "APPROVED" or .state == "CHANGES_REQUESTED")
                | select((.body // "" | ascii_downcase | contains("deterministic current-head evidence")) | not)
                | select((.body // "" | ascii_downcase | contains("deterministic fallback approval")) | not)
                | select((.body // "" | ascii_downcase | contains("model-unavailable evidence fallback")) | not)
                | select((.body // "" | ascii_downcase | contains("did not emit a usable current-head control block")) | not)
                | select((.body // "" | ascii_downcase | contains("scope: `unsupported`")) | not)
                | select((.body // "" | ascii_downcase | contains("model-pool outcome: `unknown`")) | not)]'''
NEW_FILTER = '''                | select(
                    .state == "CHANGES_REQUESTED"
                    or (
                        .state == "APPROVED"
                        and ((.body // "" | ascii_downcase | contains("deterministic current-head evidence")) | not)
                        and ((.body // "" | ascii_downcase | contains("deterministic fallback approval")) | not)
                        and ((.body // "" | ascii_downcase | contains("model-unavailable evidence fallback")) | not)
                        and ((.body // "" | ascii_downcase | contains("did not emit a usable current-head control block")) | not)
                        and ((.body // "" | ascii_downcase | contains("scope: `unsupported`")) | not)
                        and ((.body // "" | ascii_downcase | contains("model-pool outcome: `unknown`")) | not)
                    )
                  )]'''
OLD_TIME = '''          new_evidence="$(jq -nr --arg review "$review_submitted_at" --arg started "$REQUIRED_RUN_STARTED_AT" 'try (($review | fromdateiso8601) > ($started | fromdateiso8601)) catch false')"'''
NEW_TIME = '''          # GitHub review/run timestamps are second-granularity. Equality can mean the review
          # arrived later within the same second, so accept equality for exact-head evidence;
          # older seconds remain ineligible and all PR/head/state checks above still fail closed.
          new_evidence="$(jq -nr --arg review "$review_submitted_at" --arg started "$REQUIRED_RUN_STARTED_AT" 'try (($review | fromdateiso8601) >= ($started | fromdateiso8601)) catch false')"'''
OLD_COMMENT = '''    # `converted_to_draft` is included so a PR going draft mid-poll fires a
    # fresh run of this same workflow: the head-scoped concurrency group below
    # (`cancel-in-progress: true`) cancels any in-flight non-draft
    # "Fail closed without a current-head OpenCode verdict" poll for that
    # exact same head. Every non-closed admission path revalidates the live
    # PR/head/state before dispatching, exempting, or polling so out-of-order
    # draft/ready/closed events cannot publish stale evidence or wait on an
    # impossible verdict.'''
NEW_COMMENT = '''    # `converted_to_draft` is included so a PR going draft after a ready event
    # gets a fresh same-head execution. The head-scoped concurrency group below
    # (`cancel-in-progress: true`) retires any superseded same-head admission run.
    # Every non-closed path revalidates the live PR/head/state before dispatch,
    # exemption, or one-shot verdict admission, so out-of-order draft/ready/closed
    # events cannot publish stale evidence. Required verdict continuation is
    # event-driven by the authenticated exact-run wake path; this entrypoint does
    # not hold a runner in a polling loop.'''

TEST_CONTENT = r'''"""Executable regressions for event-driven OpenCode verdict reconciliation."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import textwrap

WORKFLOW = Path(".github/workflows/pr-review-merge-scheduler.yml")
HEAD = "a" * 40


def _jq_filter() -> str:
    """Extract the production jq review selector."""
    text = WORKFLOW.read_text(encoding="utf-8")
    anchor = text.index('latest_review="$(printf')
    start = text.index("            (add // [])", anchor)
    end_marker = "            | @tsv"
    end = text.index(end_marker, start) + len(end_marker)
    return textwrap.dedent(text[start:end])


def _select(reviews: list[dict[str, object]]) -> str:
    """Execute the production selector on exact-head review fixtures."""
    proc = subprocess.run(
        ["jq", "-r", "-s", "--arg", "sha", HEAD, _jq_filter()],
        input=json.dumps(reviews), text=True, capture_output=True, check=True,
    )
    return proc.stdout.strip()


def _review(state: str, body: str) -> dict[str, object]:
    """Build one exact-head OpenCode review fixture."""
    return {
        "id": 42,
        "user": {"login": "opencode-agent[bot]"},
        "commit_id": HEAD,
        "state": state,
        "body": body,
        "submitted_at": "2026-09-02T12:00:00Z",
    }


def test_marker_bearing_change_request_remains_a_formal_verdict() -> None:
    """Fallback markers invalidate approvals only, never a real change request."""
    assert _select([_review("CHANGES_REQUESTED", "deterministic fallback approval: defect remains")]).startswith("CHANGES_REQUESTED\t")


def test_marker_bearing_approval_is_not_admitted() -> None:
    """Synthetic/fallback approval markers still block APPROVED evidence."""
    assert _select([_review("APPROVED", "deterministic fallback approval")]) == ""


def test_clean_approval_is_admitted() -> None:
    """A clean exact-head approval remains a formal verdict."""
    assert _select([_review("APPROVED", "real model review")]).startswith("APPROVED\t")


def test_same_second_review_is_eligible_for_reconciliation() -> None:
    """Second-granularity timestamps must not strand a later same-second review."""
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "fromdateiso8601) >= ($started | fromdateiso8601" in text
    proc = subprocess.run(
        ["jq", "-nr", "--arg", "review", "2026-09-02T12:00:00Z", "--arg", "started", "2026-09-02T12:00:00Z", "try (($review | fromdateiso8601) >= ($started | fromdateiso8601)) catch false"],
        text=True, capture_output=True, check=True,
    )
    assert proc.stdout.strip() == "true"
'''

RECORD = '''
### OpenCode required-verdict reconciliation race repair — 2026-09-02

- **Owner / PR:** `ContextualWisdomLab/.github#1706`.
- **Root cause:** the workflow-run reconciler applied fallback-approval marker exclusions to `CHANGES_REQUESTED` reviews even though admission accepts every exact-head change request, and strict greater-than timestamp ordering could drop a later review sharing GitHub's second-granularity timestamp with the required run start.
- **Repair:** marker exclusions apply only to `APPROVED`; exact-head `CHANGES_REQUESTED` remains a formal verdict. Same-second evidence uses `>=` after live open/ready/head revalidation. Polling-era trigger comments now describe event-driven one-shot admission.
- **Regression:** `tests/test_opencode_required_verdict_reconciliation_contract.py` executes the production jq selector for marker-bearing change requests, rejected fallback approvals, clean approvals, and same-second ordering.
- **Status:** Proposed until this exact branch head receives fresh CI/security/review evidence and integrates through ordinary protected admission.
'''


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    """Replace exactly one expected source fragment or fail closed."""
    text = path.read_text(encoding="utf-8")
    if text.count(old) != 1:
        raise SystemExit(f"{label} drifted: expected exactly one match")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    """Apply permanent production, regression, and traceability repairs."""
    replace_once(SCHEDULER, OLD_FILTER, NEW_FILTER, "formal-verdict filter")
    replace_once(SCHEDULER, OLD_TIME, NEW_TIME, "review timestamp comparison")
    replace_once(OPENCODE, OLD_COMMENT, NEW_COMMENT, "OpenCode trigger comment")
    if TEST.exists():
        raise SystemExit(f"refusing to overwrite existing {TEST}")
    TEST.write_text(TEST_CONTENT, encoding="utf-8")
    baseline = BASELINE.read_text(encoding="utf-8")
    if "### OpenCode required-verdict reconciliation race repair — 2026-09-02" not in baseline:
        BASELINE.write_text(baseline.rstrip() + "\n" + RECORD, encoding="utf-8")


if __name__ == "__main__":
    main()
