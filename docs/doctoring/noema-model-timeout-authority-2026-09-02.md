# Noema elapsed-time authority correction — 2026-09-02

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
