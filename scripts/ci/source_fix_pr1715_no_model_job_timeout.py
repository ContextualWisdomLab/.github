"""One-shot exact-head repair for the merged PR #1715 timeout-policy regression."""

from __future__ import annotations

import re
from pathlib import Path

WORKFLOW = Path(".github/workflows/noema-review.yml")
TEST = Path("tests/test_noema_orchestrator_workflow_contract.py")
CHANGELOG = Path("CHANGELOG.md")
ARCHITECTURE = Path("ARCHITECTURE.md")
ADR = Path("docs/adr/0003-contextual-orchestrator-vendored-free-zdr.md")
BASELINE = Path("docs/product-technical-gap-baseline.md")
DOCTORING = Path("docs/doctoring/noema-model-timeout-authority-2026-09-02.md")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    """Replace one literal block and fail closed when branch contents moved."""
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"PR1715 successor {label}: expected one literal block, found {count}")
    return text.replace(old, new, 1)


def append_once(path: Path, marker: str, section: str) -> None:
    """Append one governance section while refusing duplicate doctoring."""
    text = path.read_text(encoding="utf-8")
    if marker in text:
        return
    path.write_text(text.rstrip() + "\n\n" + section.strip() + "\n", encoding="utf-8")


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
    # on GitHub Actions' external platform execution contract plus explicit API
    # failure. A shorter local deadline would be an unsupported hand-selected
    # policy rather than a measured queue-control invariant.
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
    # and configured model timeout policy; provider termination, live PR/head
    # invalidation, and explicit user/operator cancellation remain authoritative
    # stop signals. GitHub's platform execution ceiling is an external capacity
    # constraint, not a model-selection or test-time-compute policy.
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
    assert "unsupported hand-selected" in cleanup
    assert "no repository-authored wall-clock" in model
'''
    TEST.write_text(text[:start] + replacement, encoding="utf-8")


def patch_governance() -> None:
    """Synchronize change history, architecture, ADR, doctoring, and product-gap status."""
    changelog = CHANGELOG.read_text(encoding="utf-8")
    entry = (
        "- **Correct PR #1715 timeout authority regression.** Remove the inferred "
        "20-minute Noema cleanup deadline and the model-bearing 210-minute job "
        "deadline. Neither value had standards, measured-runtime, or experimentally "
        "validated provenance. The model-bearing deadline additionally contradicted "
        "ADR-0003 by allowing elapsed time alone to terminate contextual-orchestrator "
        "reasoning. GitHub's hosting ceiling remains an external capacity constraint; "
        "provider end, live-head supersession, explicit user/operator cancellation, "
        "or an explicitly configured contextual-orchestrator administrative timeout "
        "are the intentional model termination authorities.\n"
    )
    if entry.strip() not in changelog:
        changelog = replace_once(
            changelog,
            "## [Unreleased]\n",
            "## [Unreleased]\n" + entry,
            "CHANGELOG Unreleased header",
        )
        CHANGELOG.write_text(changelog, encoding="utf-8")

    append_once(
        ARCHITECTURE,
        "## Model execution timeout authority (2026-09-02)",
        '''## Model execution timeout authority (2026-09-02)

Central model-backed review jobs (`OpenCode`, `Noema`, and `Strix`) delegate model
selection and inference lifecycle to `ContextualWisdomLab/contextual-orchestrator`.
The GitHub Actions job that contains reasoning, streaming, or tool execution must
not invent a fixed elapsed-time ceiling. Intentional termination authorities are
an explicit user/operator cancellation, provider termination, superseded-head
retirement after live-head validation, or an explicitly configured
contextual-orchestrator administrative timeout. Queue/runner hygiene must be
expressed as measured control-plane contracts rather than hand-selected model
runtime budgets. GitHub's hosting limit remains an external capacity constraint,
not `.github` model policy.''',
    )

    append_once(
        ADR,
        "2026-09-02 correction: PR #1715's Noema deadlines were not a new timeout decision",
        '''- **2026-09-02 correction: PR #1715's Noema deadlines were not a new timeout decision.**
  The accepted 2026-08-31 amendment above already states that OpenCode, Noema,
  Strix, and contextual-orchestrator inference have no repository/application
  fixed wall-clock timeout. PR #1715 added `timeout-minutes: 20` to the
  housekeeping job by analogy to another queue job and `timeout-minutes: 210`
  to the model-bearing Noema job by combining an inherited allowance with an
  invented buffer. Neither local number had standards, measured-runtime, or
  experimentally validated provenance, and the model-bearing value directly
  contradicted this ADR. Both local deadlines are therefore removed. Provider
  termination, exact live-head invalidation, explicit user/operator cancellation,
  or an explicitly configured contextual-orchestrator administrative timeout
  remain intentional model termination authorities; GitHub's hosting ceiling is
  documented as an external runtime constraint rather than repository policy.''',
    )

    append_once(
        BASELINE,
        "### Noema workflow elapsed-time authority — PR #1715 successor",
        '''### Noema workflow elapsed-time authority — PR #1715 successor

- **Protected-main incident base:** `5935c8153722fe6b53bafd579b74f8f097303959`
  (merge of PR #1715).
- **Live gap:** PR #1715 introduced local `timeout-minutes: 20` and
  `timeout-minutes: 210`. The former was inferred by analogy to another queue
  job; the latter combined an inherited allowance with an invented buffer.
  Neither value had executable standards, measured-runtime, or experimentally
  validated provenance. The 210-minute value also violated ADR-0003's existing
  no-fixed-inference-timeout contract.
- **PRD goal:** preserve correctness-first long-running Noema review without
  replacing model/provider lifecycle authority with elapsed time.
- **TRD invariant:** neither Noema job invents a repository-authored local
  deadline; the model-bearing job uses `contextual-orchestrator/orchestrator/free`
  and terminates intentionally only on provider end, exact live-state
  invalidation, explicit user/operator cancellation, or an explicitly configured
  contextual-orchestrator administrative timeout. GitHub's host ceiling remains
  an external capacity constraint.
- **Context Map:** `.github` owns Actions admission, exact-head validation, and
  stale-run retirement; `ContextualWisdomLab/contextual-orchestrator` owns model
  routing and configured model timeout policy.
- **Regression:** `tests/test_noema_model_timeout_policy.py` is committed RED
  before the source repair and `test_noema_jobs_do_not_invent_repository_wall_clock_deadlines`
  rejects reintroduction on either job.
- **Status:** Proposed until the one-shot self-removes and fresh exact-head
  required Checks are GREEN.

```mermaid
flowchart LR
    PR[Exact PR head] --> GH[.github Noema control plane]
    GH --> CO[ContextualWisdomLab/contextual-orchestrator]
    CO --> MODEL[orchestrator/free model execution]
    USER[User/operator cancel] --> GH
    HEAD[Superseding PR head] --> GH
    PROVIDER[Provider termination] --> CO
    ADMIN[Configured CO admin timeout] --> CO
    GH -. no local elapsed-time deadline .-> MODEL
```

| Gap | Action | Status |
| --- | --- | --- |
| G-NOEMA-TIMEOUT-AUTHORITY | RED→remove unsupported 20/210-minute local deadlines→full GREEN→self-retire repair artifacts→fresh exact-head required Checks. | Proposed / PR #1720 |
| G-STALE-RUN-CENTRAL-AUTHORITY | PR #1717 must read central `repository_dispatch` run evidence with validated central authority; its prior verified patch publication failed closed after protected main moved. | Draft; preserve until current-main reconciliation |''',
    )

    DOCTORING.parent.mkdir(parents=True, exist_ok=True)
    DOCTORING.write_text(
        '''# Noema elapsed-time authority correction — 2026-09-02

## Incident

Protected main `5935c8153722fe6b53bafd579b74f8f097303959` merged PR #1715.
It added `timeout-minutes: 20` to Noema close cleanup and
`timeout-minutes: 210` to the model-bearing Noema job. The cleanup value was an
analogy to another queue job; the model value combined an inherited allowance
with an invented buffer. Neither number was supported by a measured runtime
SLO, standard, or experiment. The 210-minute model cutoff also contradicted the
accepted ADR-0003 no-fixed-inference-timeout amendment.

## Root cause

The change collapsed distinct failure domains into one elapsed-time mechanism:
finite housekeeping, GitHub-hosted runner capacity, provider communication,
and model reasoning. A GitHub job deadline cannot distinguish a model that is
still reasoning/streaming/calling tools from provider termination, operator
cancellation, a superseded head, or an explicitly configured model timeout.
It therefore made elapsed time itself an implicit model-policy owner.

## RED-first evidence

`tests/test_noema_model_timeout_policy.py` was committed on the canonical PR
#1720 owner branch before the source repair. Against the unmodified PR #1715
workflow it fails specifically because the model-bearing job contains
`timeout-minutes: 210`. The one-shot verifier must prove that exact failure
before it materializes the source repair.

## Repair boundary

Remove both repository-authored 20/210-minute deadlines and replace the old
positive-timeout contract. Keep `contextual-orchestrator/orchestrator/free`,
review identity, live-head validation, stale-run cancellation, and security
boundaries unchanged. Model termination authority remains provider end,
validated superseded-head cancellation, explicit user/operator cancellation,
or an explicitly configured contextual-orchestrator administrative timeout.
GitHub's documented hosting ceiling is treated as an external capacity
constraint, not a second model-policy value.

## Operational scenarios

1. A reasoning/tool-call path exceeds 210 minutes while still active: `.github`
   must not terminate it merely because elapsed time reached a local number.
2. A PR head advances: trusted live-head revalidation may retire the stale run.
3. A provider ends communication: the upstream request terminates/fails rather
   than being disguised as a local model timeout.
4. An administrator configures a contextual-orchestrator timeout: that explicit,
   auditable owner policy applies without a shadow GitHub Actions deadline.
5. Cleanup runtime becomes operationally excessive: measure the distribution
   and queue impact first, then encode an evidence-backed control-plane SLO
   rather than selecting another analogy-based number.

## References

ContextualWisdomLab. (2026, August 31). *ADR-0003: Vendored contextual-orchestrator review sidecar with governed gateway pools* (model-inference timeout amendment).

GitHub. (n.d.). *Workflow syntax for GitHub Actions*. https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax
''',
        encoding="utf-8",
    )


def main() -> None:
    """Apply production, regression, and governance repairs."""
    patch_workflow()
    patch_test()
    patch_governance()


if __name__ == "__main__":
    main()
