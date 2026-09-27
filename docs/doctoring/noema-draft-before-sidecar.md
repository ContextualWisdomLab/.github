# Noema live draft check before sidecar provisioning

Date: 2026-09-26
Repository: `ContextualWisdomLab/.github`
Workflow: `.github/workflows/noema-review.yml`, job `noema-review`

## Root cause

`Provision contextual-orchestrator review sidecar` (`scripts/ci/contextual_orchestrator_review_sidecar.sh`)
takes 10-13 minutes. Only afterwards did `Prepare Noema model verdict` run
`.github/actions/noema-review/two_phase.py --prepare-verdict-file`, whose `prepare_verdict` reads the
live pull request and returns early with `PR is draft; Noema verdict preparation skipped.` without an
envelope, so publication was skipped. Every draft run therefore held a hosted runner for ~13 minutes to
reach a decision that was available from one API call. Observed examples: newsdom-api job
108077744310 (2026-09-25) and `.github` job 106665379126 (2026-09-22). With organization Actions
concurrency saturated, that runner time delays other required checks.

## Repair

- New step `Check live pull request draft state before sidecar provisioning` (`id: live_draft`),
  placed after `Validate current pull request head` and `Resolve Noema target repository visibility`,
  for native `.github` targets only, reads `repos/<target>/pulls/<n>` with the same selected reviewer token and REST lookup the validate
  step already uses, and writes `live_draft=true|false`.
- `Provision contextual-orchestrator review sidecar`, `Provision local reviewed HWP document reader`,
  and `Prepare Noema model verdict` are gated on `steps.live_draft.outputs.live_draft != 'true'`.
- Fail open: a lookup error, malformed body, or any `draft` value other than JSON `true` yields
  `live_draft=false`, which is exactly today's path; `two_phase.py` keeps its own draft check.
- Downstream steps are unchanged. They already require `steps.noema_prepare.outputs.prepared == 'true'`
  (publication token refresh, publish) or `failure()` (transport re-dispatch, sidecar evidence upload),
  so unset prepare outputs mean "publication skipped", the state a draft already produced. The job
  concludes success for drafts, as before.

## Ready-event recovery boundary

The organization ruleset launches this required workflow in other repositories
only for opened/synchronize/reopened, never `ready_for_review`. The early Draft
exemption therefore applies only when both execution and target repository are
`ContextualWisdomLab/.github`. Its native Ready event re-enters the workflow on
the same head and its live lookup permits model work.

Ruleset consumer runs and central dispatches targeting a consumer bypass the
early exemption. They retain the existing sidecar and verdict-preparation path,
including its later live Draft check. This preserves the opportunity to review
a PR marked Ready during provisioning. It does not claim that a consumer PR
marked Ready after the existing final Draft check has a new event relay; that
pre-existing consumer event-delivery gap remains separate work.

## Regression coverage

`tests/test_noema_draft_admission_before_sidecar.py` pins step ordering, the gate on each
model-heavy step, the live REST lookup and token reuse, the unchanged trigger list, the absence of
`github.event.pull_request.draft`, and executes the step with a fake `gh` for draft, ready, lookup
failure, and malformed/non-boolean `draft` bodies.
