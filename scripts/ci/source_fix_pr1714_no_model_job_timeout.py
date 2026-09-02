"""One-shot repair for PR #1714's model-backed autofix no-heuristics contract."""

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
    """Remove repository-authored model termination, compute, capability, and evidence heuristics."""
    text = WORKFLOW.read_text(encoding="utf-8")
    timeout_old = '''    # Bound the job well short of GitHub's 360-minute platform default. Setup
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
    timeout_new = '''    # This job is model-backed through contextual-orchestrator/orchestrator/free
    # and therefore has no repository-owned wall-clock timeout. Provider end,
    # explicit cancellation, and the workflow's exact live-head/state guards
    # are authoritative; elapsed time alone must not terminate reasoning,
    # streaming, or tool work. Queue pressure is handled by the scheduler's
    # stale-head dedupe/cancellation rather than by killing current-head work.
'''
    text = replace_once(text, timeout_old, timeout_new, "autofix timeout block")

    text = replace_once(
        text,
        '                "reasoningEffort": "high",\n',
        "",
        "repository-authored reasoning effort",
    )
    text = replace_once(
        text,
        '                "steps": 12,\n',
        "",
        "repository-authored agent step budget",
    )
    capability_old = '''                    "name": "Orchestrator Free (ZDR-first zero-cost pool)",
                    "tool_call": true,
                    "reasoning": true,
                    "limit": {
                      "context": 200000,
                      "output": 32768
                    }
'''
    capability_new = '''                    "name": "Orchestrator Free (ZDR-first zero-cost pool)"
'''
    text = replace_once(
        text,
        capability_old,
        capability_new,
        "leaf model capability and context/output declarations",
    )
    text = replace_once(
        text,
        '          $(sed -n \'1,260p\' "$RUNNER_TEMP/pr-review-autofix-context.md")\n',
        '          $(cat "$RUNNER_TEMP/pr-review-autofix-context.md")\n',
        "review-context line quota",
    )
    WORKFLOW.write_text(text, encoding="utf-8")


def patch_test() -> None:
    """Replace the timeout-positive regression with fail-closed authority contracts."""
    text = TEST.read_text(encoding="utf-8")
    marker = "def test_autofix_job_has_a_bounded_runtime() -> None:\n"
    start = text.find(marker)
    if start < 0 or text.find(marker, start + 1) >= 0:
        raise SystemExit("PR1714 stale timeout test marker moved or duplicated")
    replacement = '''def test_autofix_model_job_delegates_termination_and_compute_to_orchestrator() -> None:
    """Leaf OpenCode config must not invent model-time or test-time-compute authority."""
    workflow = _workflow_text()
    job = workflow.split("  autofix:\\n", maxsplit=1)[1]
    job_header = job.split("    steps:\\n", maxsplit=1)[0]

    assert "timeout-minutes:" not in job_header
    assert '"model": "contextual-orchestrator/orchestrator/free"' in workflow
    assert '"reasoningEffort":' not in workflow
    assert '"steps": 12' not in workflow
    assert '"tool_call": true' not in workflow
    assert '"reasoning": true' not in workflow
    assert '"limit": {' not in workflow
    assert "no repository-owned wall-clock timeout" in job_header
    assert "cancel-in-progress: false" in workflow


def test_autofix_review_context_is_not_sampled_by_a_fixed_line_quota() -> None:
    """Exact review evidence must reach the model without a repository-authored line cutoff."""
    workflow = _workflow_text()

    assert "sed -n '1,260p'" not in workflow
    assert '$(cat "$RUNNER_TEMP/pr-review-autofix-context.md")' in workflow
'''
    TEST.write_text(text[:start] + replacement, encoding="utf-8")


def append_traceability() -> None:
    """Document the model-authority and complete-evidence boundary."""
    changelog = CHANGELOG.read_text(encoding="utf-8")
    note = (
        "\n- PR #1714: reject repository-authored OpenCode autofix wall-clock, reasoning-effort, "
        "agent-step, capability/context/output, and fixed review-line allocation. The leaf requests "
        "only `orchestrator/free`; contextual-orchestrator owns verified capability/routing/test-time "
        "compute and the full collected review evidence is passed without a hand-selected line quota.\n"
    )
    if "PR #1714: reject repository-authored OpenCode autofix wall-clock" not in changelog:
        CHANGELOG.write_text(changelog + note, encoding="utf-8")

    baseline = BASELINE.read_text(encoding="utf-8")
    section = '''

### OpenCode autofix orchestration authority — PR #1714

- **Root cause:** the leaf workflow proposed `timeout-minutes: 25` and also carried repository-authored `reasoningEffort: high`, a 12-step agent budget, asserted tool/reasoning capabilities, fixed context/output limits, and a 260-line review-context cutoff. None of those leaf allocations had executable research/model evidence establishing them as decision authority.
- **Owner boundary:** `.github` requests exactly `contextual-orchestrator/orchestrator/free` through the gateway token. contextual-orchestrator owns provider discovery, verified capability admission, routing, and research-backed test-time compute; the leaf does not invent provider/model capability or compute limits.
- **Evidence contract:** the complete review context produced by the governed collector is passed to the model. If contextual-orchestrator cannot admit/serve the request under its verified capability/privacy/free-pool contracts, the path fails closed rather than silently sampling evidence or selecting a paid/provider fallback.
- **Termination contract:** provider completion, explicit cancellation, and exact live-head/state guards end model work. Scheduler stale-head dedupe/cancellation handles queue waste without terminating the sole current-head model run by elapsed time.
- **Regression:** `test_autofix_model_job_delegates_termination_and_compute_to_orchestrator` and `test_autofix_review_context_is_not_sampled_by_a_fixed_line_quota` forbid reintroduction of those leaf heuristics while preserving the exact `orchestrator/free` contract.
- **Status:** Proposed until the one-shot source repair self-removes and fresh exact-head Checks are GREEN.
'''
    if "### OpenCode autofix orchestration authority — PR #1714" not in baseline:
        BASELINE.write_text(baseline + section, encoding="utf-8")


def main() -> None:
    """Apply production, regression, and traceability changes."""
    patch_workflow()
    patch_test()
    append_traceability()


if __name__ == "__main__":
    main()
