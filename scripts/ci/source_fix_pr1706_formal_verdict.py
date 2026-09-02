"""One-shot source repair for ContextualWisdomLab/.github PR #1706.

This temporary driver performs exact-string, fail-closed mutations only. The
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


OLD_AUTHOR = '''                | select((.user.login // "" | ascii_downcase) as $user | $user == "opencode-agent" or $user == "opencode-agent[bot]")'''
NEW_AUTHOR = '''                | select((.user.login // "" | ascii_downcase) as $user | $user == "opencode-agent" or $user == "opencode-agent[bot]" or $user == "github-actions[bot]")'''
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
OLD_CONCURRENCY_TAIL = '''  # Same-head events (draft<->ready
  # transitions, a synchronize retry) still share one group, so
  # `converted_to_draft` still cancels an active same-head verdict poll.'''
NEW_CONCURRENCY_TAIL = '''  # Same-head events (draft<->ready
  # transitions, a synchronize retry) still share one group, so
  # `converted_to_draft` cancels a superseded same-head admission run.'''
OLD_CLEANUP_COMMENT = '''  cancel-superseded-opencode-review-runs:
    # Exact-head concurrency protects a newer authoritative run from delayed
    # old-head events, while the poll above now revalidates live PR identity on
    # every wait iteration so an already-running obsolete poll can self-retire
    # without consuming a second runner. This sibling job remains a defense in
    # depth for queued/requested old-head runs and for legacy runs created from
    # older workflow revisions that lack the in-loop self-retirement check.
    # Every cancellation candidate and every cancellation itself is re-verified
    # against the live PR head immediately beforehand, so a cleanup run that is
    # itself delayed/stale cannot cancel a still-authoritative run.'''
NEW_CLEANUP_COMMENT = '''  cancel-superseded-opencode-review-runs:
    # Exact-head concurrency protects a newer authoritative run from delayed
    # old-head events. One-shot verdict admission releases its runner immediately;
    # this sibling job remains defense in depth for queued/requested old-head runs
    # and legacy runs created from older workflow revisions. Every cancellation
    # candidate and every cancellation itself is re-verified against the live PR
    # head immediately beforehand, so a delayed/stale cleanup run cannot cancel a
    # still-authoritative run.'''

TEST_CONTENT = r'''"""Executable regressions for event-driven OpenCode verdict reconciliation."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import textwrap

from scripts.ci import opencode_review_receipt_gate

SCHEDULER = Path(".github/workflows/pr-review-merge-scheduler.yml")
OPENCODE = Path(".github/workflows/opencode-review.yml")
HEAD = "a" * 40


def _scheduler_jq_filter() -> str:
    """Extract the production scheduler review selector."""
    text = SCHEDULER.read_text(encoding="utf-8")
    anchor = text.index('latest_review="$(printf')
    start = text.index("            (add // [])", anchor)
    end_marker = "            | @tsv"
    end = text.index(end_marker, start) + len(end_marker)
    return textwrap.dedent(text[start:end])


def _admission_jq_filter() -> str:
    """Extract the production one-shot admission review selector."""
    text = OPENCODE.read_text(encoding="utf-8")
    anchor = text.index('verdict="$(printf')
    start = text.index("            (add // [])", anchor)
    end_marker = '              then "APPROVED" else empty end'
    end = text.index(end_marker, start) + len(end_marker)
    return textwrap.dedent(text[start:end])


def _run_filter(filter_text: str, reviews: list[dict[str, object]]) -> str:
    """Execute one production jq selector against exact-head fixtures."""
    proc = subprocess.run(
        ["jq", "-r", "-s", "--arg", "sha", HEAD, filter_text],
        input=json.dumps(reviews),
        text=True,
        capture_output=True,
        check=True,
    )
    return proc.stdout.strip()


def _scheduler_select(reviews: list[dict[str, object]]) -> str:
    """Execute the scheduler selector."""
    return _run_filter(_scheduler_jq_filter(), reviews)


def _admission_select(reviews: list[dict[str, object]]) -> str:
    """Execute the one-shot admission selector."""
    return _run_filter(_admission_jq_filter(), reviews)


def _review(
    state: str,
    body: str,
    *,
    login: str = "opencode-agent[bot]",
) -> dict[str, object]:
    """Build one exact-head formal-review fixture."""
    return {
        "id": 42,
        "user": {"login": login},
        "commit_id": HEAD,
        "state": state,
        "body": f"## Verdict\n{body}\n\nHead SHA: `{HEAD}`",
        "submitted_at": "2026-09-02T12:00:00Z",
    }


def test_marker_bearing_change_request_remains_a_formal_verdict() -> None:
    """Fallback markers invalidate approvals only, never a real change request."""
    review = _review("CHANGES_REQUESTED", "deterministic fallback approval: defect remains")
    assert _scheduler_select([review]).startswith("CHANGES_REQUESTED\t")
    assert _admission_select([review]) == "CHANGES_REQUESTED"
    assert opencode_review_receipt_gate.is_formal_receipt(
        review, HEAD, is_draft=False
    )[0]


def test_marker_bearing_approval_is_not_admitted() -> None:
    """Synthetic/fallback approval markers still block APPROVED evidence."""
    review = _review("APPROVED", "deterministic fallback approval")
    assert _scheduler_select([review]) == ""
    assert _admission_select([review]) == ""
    assert not opencode_review_receipt_gate.is_formal_receipt(
        review, HEAD, is_draft=False
    )[0]


def test_clean_approval_is_admitted() -> None:
    """A clean exact-head approval remains a formal verdict everywhere."""
    review = _review("APPROVED", "real model review")
    assert _scheduler_select([review]).startswith("APPROVED\t")
    assert _admission_select([review]) == "APPROVED"
    assert opencode_review_receipt_gate.is_formal_receipt(
        review, HEAD, is_draft=False
    )[0]


def test_github_actions_formal_receipt_reconciles_and_admits() -> None:
    """Every accepted formal publisher must be accepted by all verdict gates."""
    review = _review(
        "CHANGES_REQUESTED",
        "current-head defect remains",
        login="github-actions[bot]",
    )
    assert _scheduler_select([review]).startswith("CHANGES_REQUESTED\t")
    assert _admission_select([review]) == "CHANGES_REQUESTED"
    assert opencode_review_receipt_gate.is_formal_receipt(
        review, HEAD, is_draft=False
    )[0]


def test_same_second_review_is_eligible_for_reconciliation() -> None:
    """Second-granularity timestamps must not strand a later same-second review."""
    text = SCHEDULER.read_text(encoding="utf-8")
    assert "fromdateiso8601) >= ($started | fromdateiso8601" in text
    proc = subprocess.run(
        [
            "jq",
            "-nr",
            "--arg",
            "review",
            "2026-09-02T12:00:00Z",
            "--arg",
            "started",
            "2026-09-02T12:00:00Z",
            "try (($review | fromdateiso8601) >= ($started | fromdateiso8601)) catch false",
        ],
        text=True,
        capture_output=True,
        check=True,
    )
    assert proc.stdout.strip() == "true"
'''

RECORD = '''
### OpenCode required-verdict reconciliation race repair — 2026-09-02

- **Owner / PR:** `ContextualWisdomLab/.github#1706`.
- **Root cause:** formal-verdict authority drifted across three gates. The workflow-run reconciler applied fallback-approval marker exclusions to `CHANGES_REQUESTED`, scheduler/admission selectors omitted the `github-actions[bot]` publisher already accepted by the canonical receipt gate, and strict greater-than timestamp ordering could drop a later review sharing GitHub's second-granularity timestamp with the required run start.
- **Repair:** the receipt gate, one-shot admission, and completion reconciliation now share the formal publisher set; marker exclusions apply only to `APPROVED`; exact-head `CHANGES_REQUESTED` remains a formal verdict; same-second evidence uses `>=` only after live open/ready/head revalidation; polling-era comments describe event-driven one-shot admission instead.
- **Regression:** `tests/test_opencode_required_verdict_reconciliation_contract.py` executes both production jq selectors and the receipt gate for marker-bearing change requests, rejected fallback approvals, clean approvals, `github-actions[bot]` formal receipts, and same-second ordering.
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
    replace_once(SCHEDULER, OLD_AUTHOR, NEW_AUTHOR, "scheduler formal publisher set")
    replace_once(OPENCODE, OLD_AUTHOR, NEW_AUTHOR, "admission formal publisher set")
    replace_once(SCHEDULER, OLD_FILTER, NEW_FILTER, "formal-verdict filter")
    replace_once(SCHEDULER, OLD_TIME, NEW_TIME, "review timestamp comparison")
    replace_once(OPENCODE, OLD_COMMENT, NEW_COMMENT, "OpenCode trigger comment")
    replace_once(
        OPENCODE,
        OLD_CONCURRENCY_TAIL,
        NEW_CONCURRENCY_TAIL,
        "OpenCode concurrency comment",
    )
    replace_once(
        OPENCODE,
        OLD_CLEANUP_COMMENT,
        NEW_CLEANUP_COMMENT,
        "OpenCode cleanup comment",
    )
    if TEST.exists():
        if TEST.read_text(encoding="utf-8") != TEST_CONTENT:
            raise SystemExit(f"existing {TEST} drifted from expected RED regression")
    else:
        TEST.write_text(TEST_CONTENT, encoding="utf-8")
    baseline = BASELINE.read_text(encoding="utf-8")
    if "### OpenCode required-verdict reconciliation race repair — 2026-09-02" not in baseline:
        BASELINE.write_text(baseline.rstrip() + "\n" + RECORD, encoding="utf-8")


if __name__ == "__main__":
    main()
