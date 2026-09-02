"""Materialize and self-retire the Noema model-timeout authority repair."""

from __future__ import annotations

from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPOSITORY_ROOT / ".github" / "workflows" / "noema-review.yml"
CONTRACT_PATH = REPOSITORY_ROOT / "tests" / "test_noema_orchestrator_workflow_contract.py"
CHANGELOG_PATH = REPOSITORY_ROOT / "CHANGELOG.md"
ARCHITECTURE_PATH = REPOSITORY_ROOT / "ARCHITECTURE.md"
ADR_PATH = REPOSITORY_ROOT / "docs" / "adr" / "0003-contextual-orchestrator-vendored-free-zdr.md"
BASELINE_PATH = REPOSITORY_ROOT / "docs" / "product-technical-gap-baseline.md"
DOCTORING_PATH = REPOSITORY_ROOT / "docs" / "doctoring" / "noema-model-timeout-authority-2026-09-02.md"
SELF_PATH = Path(__file__).resolve()
TEMP_WORKFLOW_PATH = (
    REPOSITORY_ROOT / ".github" / "workflows" / "_temp_noema_model_timeout_authority.yml"
)


OLD_TIMEOUT_BLOCK = """    # Bound this job well short of GitHub's 360-minute platform default. Its
    # \"Prepare Noema model verdict\" step calls into two_phase.py's call_llm
    # via the same contextual-orchestrator gateway whose unbounded wait was
    # confirmed to stall runs for 7-20 hours in opencode-review.yml before
    # PR #1707's fix -- and noema_review_gate.py's own comment says that
    # step \"remains governed by contextual-orchestrator rather than a fixed
    # inference timeout\", so nothing upstream of this job bounds it either.
    # 210 minutes gives that step the same ~180-minute (3-hour) allowance
    # PR #1707 set for its analogous model-wait deadline -- comfortably
    # above this org's documented \"accommodate over 2 hours per model\"
    # policy (docs/product-goal-directive.md #8) -- plus a 30-minute buffer
    # for this job's other steps (tarball fetch, credential mint, the
    # superseded-run cleanup sweep, visibility-lookup retries, sidecar
    # provisioning, publication), while staying well under GitHub's default.
    timeout-minutes: 210
"""
NEW_TIMEOUT_BLOCK = """    # Model reasoning intentionally has no GitHub job-level wall-clock timeout.
    # ADR-0003 delegates termination authority to explicit user cancellation,
    # provider termination, superseded-head cancellation, or an explicitly
    # configured contextual-orchestrator administrative timeout. Mechanical
    # support jobs may remain separately bounded because they do not contain
    # model reasoning.
"""
OLD_TEST_MARKER = (
    "\ndef test_noema_review_job_has_a_bounded_runtime_above_the_two_hour_model_allowance() -> None:\n"
)

CHANGELOG_ENTRY = """- **Restore Noema model timeout authority to the contextual-orchestrator contract.** PR #1715 added `timeout-minutes: 210` to the model-bearing `noema-review` job even though ADR-0003 already requires no repository/application fixed wall-clock limit for OpenCode, Noema, Strix, or their contextual-orchestrator inference path. That job-level ceiling could terminate a legitimate long reasoning/streaming/tool call solely because elapsed time reached 210 minutes. The corrective contract was committed RED first, the model-bearing job ceiling is removed, and the separate mechanical `cancel-closed-pr-runs` 20-minute bound remains because it contains no model execution. User cancellation, provider termination, superseded-head retirement, or an explicitly configured contextual-orchestrator administrative timeout remain the valid termination authorities.
"""

ARCHITECTURE_SECTION = """

## Model execution timeout authority (2026-09-02)

Central model-bearing review jobs (`OpenCode`, `Noema`, and `Strix`) delegate model
selection and inference lifecycle to `ContextualWisdomLab/contextual-orchestrator`.
The GitHub Actions job that contains reasoning, streaming, or tool execution MUST
NOT impose a fixed elapsed-time ceiling. Legitimate termination authorities are
an explicit user/operator cancellation, provider termination, superseded-head
retirement after live-head validation, or an explicitly configured
contextual-orchestrator administrative timeout. Mechanical support jobs that do
not execute a model may use bounded `timeout-minutes` values to contain queue and
runner leakage. This distinction prevents queue hygiene from becoming an
implicit model-quality policy.
"""

ADR_AMENDMENT = """

- **2026-09-02 correction: PR #1715's 210-minute Noema job ceiling was a regression, not a new timeout decision.**
  The accepted 2026-08-31 amendment above already states that OpenCode, Noema,
  Strix, and contextual-orchestrator inference have no repository/application
  fixed wall-clock timeout. PR #1715 correctly bounded the mechanical
  `cancel-closed-pr-runs` housekeeping job, but also added
  `timeout-minutes: 210` to the model-bearing `noema-review` job. That second
  change contradicted this ADR by letting GitHub Actions terminate legitimate
  reasoning solely because elapsed time reached 210 minutes. The model-bearing
  ceiling is therefore removed. Explicit user/operator cancellation, provider
  termination, superseded-head cancellation after live-head validation, or an
  explicitly configured contextual-orchestrator administrative timeout remain
  the only intentional termination authorities; mechanical non-model support
  jobs may remain independently bounded.
"""

BASELINE_SECTION = """

## 2026-09-02 Noema model-timeout authority correction

### Current evidence

- Protected-main incident base: `5935c8153722fe6b53bafd579b74f8f097303959`
  (merge of PR #1715).
- PR #1715 correctly bounded the non-model `cancel-closed-pr-runs` housekeeping
  job at 20 minutes, but also added `timeout-minutes: 210` to the model-bearing
  `noema-review` job.
- ADR-0003 already requires no repository/application fixed wall-clock timeout
  for OpenCode, Noema, Strix, or their contextual-orchestrator inference path.
- GitHub Actions `timeout-minutes` is a process-termination boundary, so placing
  it on the model-bearing job makes elapsed time itself a reviewer termination
  authority and can truncate reasoning/streaming/tool calls.

### PRD / TRD / Context Map delta

- **PRD goal:** preserve correctness-first long-running Noema review while
  containing only non-model runner leakage.
- **TRD invariant:** the model-bearing `noema-review` job has no job-level
  `timeout-minutes`; non-model housekeeping may remain bounded. Model
  termination is owned by explicit user/operator cancellation, provider end,
  live-head supersession, or an explicitly configured contextual-orchestrator
  administrative timeout.
- **Context Map:** `.github` owns Actions admission/runner hygiene and exact-head
  evidence; `ContextualWisdomLab/contextual-orchestrator` owns model routing and
  configured model timeout policy. `.github` must not recreate that policy as a
  job wall-clock ceiling.

```mermaid
flowchart LR
    PR[Exact PR head] --> GH[.github Noema control plane]
    GH --> CO[ContextualWisdomLab/contextual-orchestrator]
    CO --> MODEL[orchestrator/free model execution]
    USER[User/operator cancel] --> GH
    HEAD[Superseding PR head] --> GH
    PROVIDER[Provider termination] --> CO
    ADMIN[Configured CO admin timeout] --> CO
    GH -. no elapsed-time model ceiling .-> MODEL
```

### Gap / Action / status

| Gap | Action | Status |
| --- | --- | --- |
| G-NOEMA-TIMEOUT-AUTHORITY | RED contract rejects any job-level timeout on the model-bearing Noema job; remove the 210-minute ceiling; keep the 20-minute non-model close-cleanup bound; update ADR/doctoring/architecture/changelog. | Repair branch; exact-head CI required before merge |
| G-STALE-RUN-CENTRAL-AUTHORITY | PR #1717 must revalidate central `repository_dispatch` runs with central read authority while preserving target-repository reads for target runs. Its first one-shot verification was GREEN but publication failed closed when protected main advanced concurrently. | Draft; rebase/reconcile publication authority after current protected-main repair |
"""

DOCTORING_TEXT = """# Noema model timeout authority correction — 2026-09-02

## Incident

Protected main `5935c8153722fe6b53bafd579b74f8f097303959` merged PR #1715.
That PR correctly bounded the mechanical `cancel-closed-pr-runs` job at 20
minutes, but also added `timeout-minutes: 210` to the model-bearing
`noema-review` job. The latter contradicted the already accepted ADR-0003
invariant that central model inference has no repository/application fixed
wall-clock timeout.

## Root cause

The change treated two different failure domains as one timeout problem:
runner leakage in finite housekeeping and long-running model reasoning. A
job-level Actions timeout is outside contextual-orchestrator and cannot
identify whether the model is still reasoning, streaming, calling tools, the
provider ended the request, an operator cancelled it, or an administrative
model timeout was explicitly configured. It therefore makes elapsed time alone
a termination authority.

## RED first

Commit `8fdae899737d511c4bab3bd76fd5500dc19035d0` added
`tests/test_noema_model_timeout_policy.py`. Against the unmodified PR #1715
workflow, the regression fails because the model-bearing job contains
`timeout-minutes: 210`. The production repair is applied only after this RED
contract exists.

## Repair boundary

The model-bearing `noema-review` job loses its 210-minute job ceiling. The
20-minute `cancel-closed-pr-runs` timeout remains: that job is a finite,
non-model Actions cleanup path and bounding it cannot truncate model reasoning.
The older test that required `120 < timeout < 360` on the model job is retired
because it encoded the defect as policy. ADR-0003, ARCHITECTURE.md, CHANGELOG.md,
and the product/technical gap baseline are synchronized with the executable
contract.

## Failure scenarios

1. A reasoning model runs for more than 210 minutes while still producing
   legitimate work: GitHub Actions must not terminate it merely for elapsed
   time.
2. A PR head is superseded: trusted live-head cancellation may retire the stale
   review without waiting for model completion.
3. A provider terminates communication: the upstream failure remains terminal
   for that provider request; the workflow must not disguise it as a wall-clock
   timeout.
4. An administrator explicitly configures a contextual-orchestrator model
   timeout: that configured policy is authoritative and auditable; `.github`
   does not shadow it with a second hard-coded timeout.
5. A non-model close cleanup hangs: its independent 20-minute job limit may
   terminate it because no model reasoning is present.

## Evidence and references

- ContextualWisdomLab. (2026, August 31). *ADR-0003: Vendored contextual-orchestrator review sidecar with governed gateway pools* (model-inference timeout amendment).
- GitHub. (n.d.). *Workflow syntax for GitHub Actions*. `timeout-minutes` defines a maximum execution duration that stops the process. https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax
- Protected-main incident commit: `5935c8153722fe6b53bafd579b74f8f097303959`.
- RED contract commit: `8fdae899737d511c4bab3bd76fd5500dc19035d0`.
"""


def _replace_once(text: str, old: str, new: str, *, label: str) -> str:
    """Replace one exact source fragment and fail closed on drift."""
    occurrence_count = text.count(old)
    if occurrence_count != 1:
        raise RuntimeError(
            f"{label} expected exactly one source fragment; observed {occurrence_count}"
        )
    return text.replace(old, new, 1)


def _append_once(path: Path, marker: str, addition: str) -> None:
    """Append a dated governance section only when it is not already present."""
    text = path.read_text(encoding="utf-8")
    if marker in text:
        return
    path.write_text(text.rstrip() + addition.rstrip() + "\n", encoding="utf-8")


def main() -> None:
    """Apply the verified timeout repair and remove one-shot implementation files."""
    workflow_text = WORKFLOW_PATH.read_text(encoding="utf-8")
    WORKFLOW_PATH.write_text(
        _replace_once(
            workflow_text,
            OLD_TIMEOUT_BLOCK,
            NEW_TIMEOUT_BLOCK,
            label="Noema model timeout block",
        ),
        encoding="utf-8",
    )

    contract_text = CONTRACT_PATH.read_text(encoding="utf-8")
    marker_count = contract_text.count(OLD_TEST_MARKER)
    if marker_count != 1:
        raise RuntimeError(
            "legacy Noema timeout contract expected exactly once; "
            f"observed {marker_count}"
        )
    contract_prefix, _legacy_contract = contract_text.split(OLD_TEST_MARKER, 1)
    CONTRACT_PATH.write_text(contract_prefix.rstrip() + "\n", encoding="utf-8")

    changelog_text = CHANGELOG_PATH.read_text(encoding="utf-8")
    if CHANGELOG_ENTRY.strip() not in changelog_text:
        changelog_text = _replace_once(
            changelog_text,
            "## [Unreleased]\n",
            "## [Unreleased]\n" + CHANGELOG_ENTRY,
            label="CHANGELOG Unreleased header",
        )
        CHANGELOG_PATH.write_text(changelog_text, encoding="utf-8")

    _append_once(
        ARCHITECTURE_PATH,
        "## Model execution timeout authority (2026-09-02)",
        ARCHITECTURE_SECTION,
    )
    _append_once(
        ADR_PATH,
        "2026-09-02 correction: PR #1715's 210-minute Noema job ceiling",
        ADR_AMENDMENT,
    )
    _append_once(
        BASELINE_PATH,
        "## 2026-09-02 Noema model-timeout authority correction",
        BASELINE_SECTION,
    )
    DOCTORING_PATH.write_text(DOCTORING_TEXT, encoding="utf-8")

    TEMP_WORKFLOW_PATH.unlink(missing_ok=True)
    SELF_PATH.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
