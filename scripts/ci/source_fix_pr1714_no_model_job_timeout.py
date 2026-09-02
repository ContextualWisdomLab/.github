"""One-shot repair for PR #1714's model-backed autofix timeout contract."""

from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(".github/workflows/pr-review-autofix.yml")
TEST = Path("tests/test_pr_review_autofix_writer_security_contract.py")
CHANGELOG = Path("CHANGELOG.md")
BASELINE = Path("docs/product-technical-gap-baseline.md")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    """Replace one literal block and fail closed if the exact head moved semantically."""
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"PR1714 {label}: expected one literal block, found {count}")
    return text.replace(old, new, 1)


def patch_workflow() -> None:
    """Remove elapsed-time termination while retaining live-head safety controls."""
    text = WORKFLOW.read_text(encoding="utf-8")
    old = '''    # Bound the job well short of GitHub's 360-minute platform default. Setup
    # (checkout, OIDC token exchange, OpenCode CLI install, context collection)
    # is API/IO-bound and normally finishes in a few minutes; the one
    # `opencode run` call (12 agent steps, single fixed model, no
    # multi-provider fallback pool unlike opencode-review-dispatch.yml's
    # review job) is the dominant cost, followed by fast local validation
    # and a single git commit/push. 25 minutes gives that single LLM run
    # generous per-step room while still failing a hung invocation well
    # before the platform cap.
    timeout-minutes: 25
'''
    new = '''    # This job is model-backed through contextual-orchestrator/orchestrator/free
    # and therefore has no repository-owned wall-clock timeout. Provider end,
    # explicit cancellation, and the workflow's exact live-head/state guards
    # are authoritative; elapsed time alone must not terminate reasoning,
    # streaming, or tool work. Queue pressure is handled by the scheduler's
    # stale-head dedupe/cancellation rather than by killing current-head work.
'''
    WORKFLOW.write_text(
        replace_once(text, old, new, "autofix timeout block"), encoding="utf-8"
    )


def patch_test() -> None:
    """Replace stale timeout-positive regression with the model authority contract."""
    text = TEST.read_text(encoding="utf-8")
    marker = "def test_autofix_job_has_a_bounded_runtime() -> None:\n"
    start = text.find(marker)
    if start < 0 or text.find(marker, start + 1) >= 0:
        raise SystemExit("PR1714 stale timeout test marker moved or duplicated")
    replacement = '''def test_autofix_model_job_has_no_elapsed_time_termination() -> None:
    """OpenCode autofix delegates model completion to orchestrator/provider authority."""
    workflow = _workflow_text()
    job = workflow.split("  autofix:\\n", maxsplit=1)[1]
    job_header = job.split("    steps:\\n", maxsplit=1)[0]

    assert "timeout-minutes:" not in job_header
    assert "contextual-orchestrator/orchestrator/free" in workflow
    assert "no repository-owned wall-clock timeout" in job_header
    assert "cancel-in-progress: false" in workflow
'''
    TEST.write_text(text[:start] + replacement, encoding="utf-8")


def append_traceability() -> None:
    """Document the queue-pressure/model-termination boundary."""
    changelog = CHANGELOG.read_text(encoding="utf-8")
    note = (
        "\n- PR #1714: reject a 25-minute GitHub job timeout on model-backed OpenCode "
        "autofix; keep `orchestrator/free` provider completion and exact-head/explicit "
        "cancellation as termination authority, with stale-run pressure handled by the scheduler.\n"
    )
    if "PR #1714: reject a 25-minute GitHub job timeout" not in changelog:
        CHANGELOG.write_text(changelog + note, encoding="utf-8")

    baseline = BASELINE.read_text(encoding="utf-8")
    section = '''

### OpenCode autofix model-job timeout authority — PR #1714

- **Root cause:** the queue-capacity repair proposed `timeout-minutes: 25` around a current-head OpenCode model job, converting elapsed wall time into model termination authority.
- **Contract:** OpenCode remains fixed to `contextual-orchestrator/orchestrator/free`; provider completion, explicit cancellation, and exact live-head/state guards end work. Scheduler stale-head dedupe/cancellation handles queue waste without killing the sole current-head model run by elapsed time.
- **Regression:** `test_autofix_model_job_has_no_elapsed_time_termination` requires no job-level timeout while preserving `cancel-in-progress: false` for the mutation-capable writer lane.
- **Status:** Implemented on the PR #1714 writer branch; regenerate exact-head checks/reviews after materialization.
'''
    if "### OpenCode autofix model-job timeout authority — PR #1714" not in baseline:
        BASELINE.write_text(baseline + section, encoding="utf-8")


def main() -> None:
    """Apply production, regression, and traceability changes."""
    patch_workflow()
    patch_test()
    append_traceability()


if __name__ == "__main__":
    main()
