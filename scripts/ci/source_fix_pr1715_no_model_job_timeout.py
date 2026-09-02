"""One-shot exact-head repair for PR #1715's Noema model timeout contract."""

from __future__ import annotations

import re
from pathlib import Path

WORKFLOW = Path(".github/workflows/noema-review.yml")
TEST = Path("tests/test_noema_orchestrator_workflow_contract.py")
CHANGELOG = Path("CHANGELOG.md")
BASELINE = Path("docs/product-technical-gap-baseline.md")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    """Replace one literal block and fail closed when branch contents moved."""
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"PR1715 {label}: expected one literal block, found {count}")
    return text.replace(old, new, 1)


def patch_workflow() -> None:
    """Keep bounded cleanup but remove elapsed-time authority from model work."""
    text = WORKFLOW.read_text(encoding="utf-8")
    old = '''    # Bound this job well short of GitHub's 360-minute platform default. Its
    # "Prepare Noema model verdict" step calls into two_phase.py's call_llm
    # via the same contextual-orchestrator gateway whose unbounded wait was
    # confirmed to stall runs for 7-20 hours in opencode-review.yml before
    # PR #1707's fix -- and noema_review_gate.py's own comment says that
    # step "remains governed by contextual-orchestrator rather than a fixed
    # inference timeout", so nothing upstream of this job bounds it either.
    # 210 minutes gives that step the same ~180-minute (3-hour) allowance
    # PR #1707 set for its analogous model-wait deadline -- comfortably
    # above this org's documented "accommodate over 2 hours per model"
    # policy (docs/product-goal-directive.md #8) -- plus a 30-minute buffer
    # for this job's other steps (tarball fetch, credential mint, the
    # superseded-run cleanup sweep, visibility-lookup retries, sidecar
    # provisioning, publication), while staying well under GitHub's default.
    timeout-minutes: 210
'''
    new = '''    # Model-backed Noema intentionally has no job-level wall-clock timeout.
    # contextual-orchestrator/orchestrator/free owns provider termination;
    # GitHub admission must not stop reasoning, streaming, or tool work only
    # because elapsed time crossed a repository-side deadline. Stale heads,
    # closed/draft PRs, provider completion, and explicit cancellation remain
    # authoritative termination signals. The non-model cleanup job above is
    # independently bounded because it performs only GitHub API housekeeping.
'''
    WORKFLOW.write_text(
        replace_once(text, old, new, "model job timeout block"), encoding="utf-8"
    )


def patch_test() -> None:
    """Replace the stale timeout-positive assertion with the owner contract."""
    text = TEST.read_text(encoding="utf-8")
    marker = "def test_noema_review_job_has_a_bounded_runtime_above_the_two_hour_model_allowance() -> None:\n"
    start = text.find(marker)
    if start < 0 or text.find(marker, start + 1) >= 0:
        raise SystemExit("PR1715 stale model-timeout test marker moved or duplicated")
    replacement = '''def test_noema_review_model_job_has_no_elapsed_time_termination() -> None:
    """Model-backed Noema delegates termination to orchestrator/provider authority."""
    workflow = workflow_text("noema-review.yml")
    job = workflow.split("  noema-review:\\n", 1)[1]

    assert re.search(r"^    timeout-minutes:", job, flags=re.MULTILINE) is None
    assert "contextual-orchestrator/orchestrator/free" in workflow
    assert "Model-backed Noema intentionally has no job-level wall-clock timeout" in job
    assert "timeout-minutes: 20" in workflow.split(
        "  cancel-closed-pr-runs:\\n", 1
    )[1].split("\\n  noema-review:\\n", 1)[0]
'''
    TEST.write_text(text[:start] + replacement, encoding="utf-8")


def append_traceability() -> None:
    """Record why support housekeeping may be bounded while model work may not."""
    changelog_note = (
        "\n- PR #1715: keep the non-model Noema close-cleanup job bounded, but remove "
        "the proposed 210-minute job timeout from model-backed `noema-review`; "
        "`orchestrator/free`/provider completion, live PR/head state, or explicit "
        "cancellation are the termination authorities rather than elapsed time.\n"
    )
    changelog = CHANGELOG.read_text(encoding="utf-8")
    if "PR #1715: keep the non-model Noema close-cleanup job bounded" not in changelog:
        CHANGELOG.write_text(changelog + changelog_note, encoding="utf-8")

    baseline_note = '''

### Noema model-job timeout authority — PR #1715

- **Root cause:** a queue-operability repair proposed `timeout-minutes: 210` on the model-backed `noema-review` job, turning elapsed wall time into an admission/model termination authority.
- **Contract:** the lightweight closed-PR Actions cleanup remains bounded, while Noema model work has no repository-owned wall-clock cutoff. `orchestrator/free` and its upstream provider own normal model completion; live PR/head validation, provider end, or explicit cancellation remain authoritative stop conditions.
- **Regression:** `test_noema_review_model_job_has_no_elapsed_time_termination` rejects a job-level timeout on the model job while retaining the 20-minute bound on non-model cleanup.
- **Status:** Implemented on the PR #1715 writer branch; exact-head CI/review must be regenerated after the one-shot repair commit.
'''
    baseline = BASELINE.read_text(encoding="utf-8")
    if "### Noema model-job timeout authority — PR #1715" not in baseline:
        BASELINE.write_text(baseline + baseline_note, encoding="utf-8")


def main() -> None:
    """Apply the minimal owner repair and its permanent regression/docs."""
    patch_workflow()
    patch_test()
    append_traceability()


if __name__ == "__main__":
    main()
