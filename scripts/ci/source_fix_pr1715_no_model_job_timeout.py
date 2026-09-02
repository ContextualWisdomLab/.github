"""One-shot exact-head repair for the merged PR #1715 timeout-policy regression."""

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
        raise SystemExit(f"PR1715 successor {label}: expected one literal block, found {count}")
    return text.replace(old, new, 1)


def patch_workflow() -> None:
    """Remove repository-authored elapsed-time termination from both Noema jobs."""
    text = WORKFLOW.read_text(encoding="utf-8")
    cleanup_old = '''    # Bound this job well short of GitHub's 360-minute platform default. Its
    # only step is a single-repository, status-filtered gh api --paginate
    # list-and-cancel sweep (up to 3 passes x 5 statuses), no branch update
    # or merge -- lighter than pr-review-merge-scheduler.yml's scan-pr-queue
    # job (PR #1702), which got timeout-minutes: 30 for a comparable
    # single-repo scan that also dispatches a review and updates a branch.
    timeout-minutes: 20
'''
    cleanup_new = '''    # No repository-authored wall-clock cutoff: this housekeeping job relies
    # on GitHub Actions' platform execution contract plus explicit API failure.
    # A shorter local deadline would be an unsupported hand-selected policy.
'''
    text = replace_once(text, cleanup_old, cleanup_new, "cleanup timeout block")

    model_old = '''    # Bound this job well short of GitHub's 360-minute platform default. Its
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
    model_new = '''    # Model-backed Noema intentionally has no repository-authored wall-clock
    # timeout. contextual-orchestrator/orchestrator/free owns provider routing
    # and normal model completion; live PR/head state and explicit cancellation
    # remain authoritative stop signals. GitHub's platform execution ceiling is
    # an external runtime constraint, not a model-selection or compute policy.
'''
    text = replace_once(text, model_old, model_new, "model job timeout block")
    WORKFLOW.write_text(text, encoding="utf-8")


def patch_test() -> None:
    """Replace timeout-positive regressions with no-local-deadline contracts."""
    text = TEST.read_text(encoding="utf-8")
    marker = "def test_cancel_closed_pr_runs_has_a_bounded_runtime() -> None:\n"
    start = text.find(marker)
    if start < 0 or text.find(marker, start + 1) >= 0:
        raise SystemExit("PR1715 successor timeout-test marker moved or duplicated")
    replacement = '''def test_noema_jobs_do_not_invent_repository_wall_clock_deadlines() -> None:
    """Noema model/support jobs must not encode hand-selected elapsed-time cutoffs."""
    workflow = workflow_text("noema-review.yml")
    cleanup = workflow.split("  cancel-closed-pr-runs:\\n", 1)[1].split(
        "\\n  noema-review:\\n", 1
    )[0]
    model = workflow.split("  noema-review:\\n", 1)[1]

    assert re.search(r"^    timeout-minutes:", cleanup, flags=re.MULTILINE) is None
    assert re.search(r"^    timeout-minutes:", model, flags=re.MULTILINE) is None
    assert "contextual-orchestrator/orchestrator/free" in workflow
    assert "unsupported hand-selected policy" in cleanup
    assert "no repository-authored wall-clock" in model
'''
    TEST.write_text(text[:start] + replacement, encoding="utf-8")


def append_traceability() -> None:
    """Record the causal owner and replacement authority."""
    changelog = CHANGELOG.read_text(encoding="utf-8")
    note = (
        "\n- Successor to merged PR #1715: remove repository-authored 20/210-minute "
        "Noema workflow deadlines. GitHub's platform runtime contract governs ordinary "
        "Actions execution; contextual-orchestrator/provider completion, exact live state, "
        "and explicit cancellation govern model work. No inferred local buffer remains.\n"
    )
    if "Successor to merged PR #1715: remove repository-authored 20/210-minute" not in changelog:
        CHANGELOG.write_text(changelog + note, encoding="utf-8")

    baseline = BASELINE.read_text(encoding="utf-8")
    section = '''

### Noema workflow elapsed-time authority — PR #1715 successor

- **Live gap:** merged PR #1715 introduced local `timeout-minutes: 20` and `timeout-minutes: 210`. The former was inferred by analogy to another queue job; the latter combined an inherited 180-minute allowance with an invented 30-minute buffer. Neither value had executable mathematical, statistical, psychometric, standards, or experimentally validated provenance.
- **Causal owner:** `.github/.github/workflows/noema-review.yml`; contextual-orchestrator remains owner of model routing/provider completion and test-time-compute policy.
- **Repair:** remove both repository-authored deadlines. Non-model housekeeping uses GitHub Actions' documented platform execution contract and API failures; model-backed Noema additionally uses exact PR/head state, explicit cancellation, and contextual-orchestrator/provider completion. No paid/provider/model fallback is introduced.
- **Regression:** `test_noema_jobs_do_not_invent_repository_wall_clock_deadlines` rejects local timeout policy on both jobs and retains the exact `orchestrator/free` routing contract.
- **Status:** Proposed until this one-shot self-removes and fresh exact-head required Checks are GREEN.
'''
    if "### Noema workflow elapsed-time authority — PR #1715 successor" not in baseline:
        BASELINE.write_text(baseline + section, encoding="utf-8")


def main() -> None:
    """Apply production, regression, and traceability repairs."""
    patch_workflow()
    patch_test()
    append_traceability()


if __name__ == "__main__":
    main()
