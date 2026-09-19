# Doctoring: OpenCode same-head in-flight dispatch dedupe (2026-09-19)

- **Date:** 2026-09-19
- **Incident:** ContextualWisdomLab/pg-erd-cloud Required OpenCode Review run
  `35412595263` job `105868602312` (PR #1183 head `9a759df24e8b714348ac2d240491f74ee3fc852d`,
  workflow pin `64aa08d7…`). Job created `08:30:15Z`, started `12:41:37Z`, completed
  `12:41:46Z` → **4h11m22s queue / ~9s execution**. Steps: review dispatch succeeded
  `12:41:39–43`, then fail-closed `12:41:45` with “No APPROVED or CHANGES_REQUESTED from
  opencode-agent on the current head… will rerun this failed job after publishing an
  authenticated exact-head verdict.” Same handshake as appguardrail#1247.
- **Shared owner:** `ContextualWisdomLab/.github` (`opencode-review.yml` +
  `opencode-review-dispatch.yml`). Callers are org ruleset `18156473` targets (all default
  branches except documented exclusions) — do not patch leaf repos.

## What is *not* broken

- Fail-closed without a formal exact-head verdict (intentional; must not become success).
- Wake via `required_run_id` + `path=.github/workflows/opencode-review.yml` +
  `event=pull_request_target` + exact `head_sha` (live incident run matches; not an
  org-ruleset path mismatch).
- Releasing the runner instead of polling the multi-hour model
  (`docs/pr-review-and-merge-procedure.md`).

## What *is* broken under saturation

1. **Duplicate same-head `repository_dispatch`.** Every new required admission after a
   completed fail-closed handshake posts another dispatch when the receipt is still
   missing. Dispatch concurrency is `opencode-review-dispatch-${repo}-${pr}` with
   `cancel-in-progress: true`, so the new event **cancels** the prior queued/running
   review for that PR — including a multi-hour review that had not yet woken the
   required check.
2. **Queue amplification.** Each cancelled review + each required job that waits hours
   only to spend 9s on dispatch+fail burns org runner admission without advancing a
   verdict (measurement pattern in `docs/doctoring/actions-capacity-root-cause-20260917.md`).

The scheduler already skips with `already_running` via `active_opencode_run_refs`; the
**required** entrypoint did not.

## Minimal fix

- Add `scripts/ci/opencode_inflight_dispatch_gate.py` — exact-equality match central
  `repository_dispatch` runs whose `display_title` is
  `OpenCode Review Dispatch {repo}#{pr}@{40-hex head}`.
- Inspect every GitHub-defined nonterminal workflow status: `queued`, `in_progress`,
  `requested`, `waiting`, and `pending`; paginate every result page. The REST
  contract caps `per_page` at 100, so first-page admission is not complete evidence.
- In `opencode-review.yml` “Request current-head OpenCode review execution”, after OIDC
  app-token exchange and before `dispatches` POST: if gate returns `present`, skip the
  POST; always continue to the fail-closed verdict step (no success without receipt).
- Tests: `tests/test_opencode_inflight_dispatch_gate.py` plus updates to
  `tests/test_opencode_required_verdict_regression.py`.

## Forbidden

- Marking the required check success without an `opencode-agent` /
  `opencode-agent[bot]` / formal receipt-gate APPROVED or CHANGES_REQUESTED on the
  exact head.
- Weakening wake identity checks or dropping `required_run_id` binding.
- Per-leaf “just re-run the job” as the repair.

## Before / after (measurement intent)

| Metric | Before (incident) | After (expected) |
|--------|-------------------|------------------|
| Same-head duplicate dispatch while prior queued/running | Allowed (cancels prior) | Skipped (`present`) |
| Required job still fail-closed without verdict | Yes | Yes (unchanged) |
| Wake after formal receipt | `rerun-failed-jobs` on `required_run_id` | Unchanged |
| Queue waste class | Hours → 9s fail → re-dispatch cancel loop | Hours → 9s fail **without** cancelling in-flight review |

## Related

- appguardrail#1247 tracker: `TRACK-appguardrail-1247.md`
- Capacity root cause: `docs/doctoring/actions-capacity-root-cause-20260917.md`
- CodeQL wake-once parallel (not this PR): `.github#2051`


## Exact-identity follow-up

The initial implementation admitted four false boundaries:

- repository components containing repeated dots or ending in a dot;
- a run title with arbitrary bytes after the 40-hex head;
- only `queued` and `in_progress`, omitting GitHub's active `requested`,
  `waiting`, and `pending` states;
- only the first 100 runs during the saturation incident class this gate exists to fix.

RED commit `5d1ab119d4c0140f68dfef555d2818ac96e0616c` records all four
contracts. GREEN commit `e8b6570b8c9c5930178717c326fc20583e37dcab`
uses canonical repository components, exact title equality, GitHub's complete
nonterminal status set, and `gh api --paginate --slurp`.

Exact remote verification compiled source and tests (**2/2**) and passed
**10/10** focused contract assertions. Full pytest is not claimed because the
isolated verifier does not provide pytest; fresh hosted exact-head Checks remain
mandatory.

## Authoritative source

GitHub. (2026). *REST API endpoints for workflow runs: List workflow runs for a
repository*. Retrieved September 19, 2026, from
https://docs.github.com/en/rest/actions/workflow-runs?apiVersion=2022-11-28#list-workflow-runs-for-a-repository

## Serialized-owner follow-up

Review of exact `9535e7a38f3df8ce5a2d438b14484a39c2e4b6e9` found that
list-before-POST was only a best-effort observation: two required admissions
could both observe `missing` before either dispatch became visible, and the
second event would cancel the first under unconditional PR-scoped
`cancel-in-progress: true`. It also listed every central
`repository_dispatch` workflow, so an unrelated workflow with the same
presentation title could suppress the real review.

RED `b6c5a19243a1d89a1afbaf8aff14fb5eceebd4e0` adds the concurrent-missing,
canonical-workflow identity, stale-head supersession, and duplicate-receipt
retirement contracts. The causal repair:

- lists runs only from the canonical
  `opencode-review-dispatch.yml` workflow endpoint;
- distinguishes exact-head `present`, prior-head `stale`, and `missing`;
- carries `cancel_in_progress=false` for same-head/missing admissions, so the
  PR-scoped workflow concurrency serializes racers without cancelling the active
  owner;
- carries `true` only when a canonical prior-head run was observed, preserving
  current-head supersession;
- reuses the trusted formal receipt predicate at the start of the serialized
  workflow and retires a queued duplicate before coverage/model review. If the
  first owner failed without a receipt, the queued run remains eligible to
  recover.

The formal exact-head receipt remains the only success authority. In-flight or
serialized state never produces approval. Exact
`ee56022c102df620b3467e8e69f59bba5168c4bf` verification: Python compile
**2/2**, focused policy assertions **18/18**, extracted Bash syntax **2/2**, and
YAML parse **2/2**. The isolated runtime has no pytest package, so full pytest is
not claimed; hosted exact-head Checks and independent current-head review remain
mandatory.

## Pending-run replacement follow-up (2026-09-20)

Review of exact `017b563c2effd66caec8e223372d41d11cbfb7a9` found that
conditional `cancel-in-progress: false` did not preserve a second pending run.
GitHub's default concurrency policy permits at most one running and one pending
run in a group; a newly queued run cancels the existing pending run. Therefore
the earlier same-head serialization claim was incomplete even though running
owners were no longer cancelled.

RED `3f1360e4236220c1ea7e56b6854a346484497129` records the
pending-owner preservation contract. The minimal repair is:

- GREEN `dfff8b386bc8fd40a9bca153be85cf0ad09c7581` sets the
  PR-scoped central workflow to the platform-native `queue: max` policy;
- GREEN `24b24525a4ac7eaf0b9667c34e215a1d692d997b` removes the
  dynamic cancellation field from the caller and dispatch payload;
- regression alignment `a33c0b4f0ddc0b2ba297cf3ce8cd3d775f55df87`
  preserves both pending and running owners.

A stale event is still rejected when its first central job obtains live
pull-request metadata, before the formal-receipt check, coverage, or model
execution. That rejection alone is not timely stale-work retirement: if different
heads share the workflow-level queue group, a new head cannot reach the existing
PR-scoped `opencode-review-target` cancellation boundary until the stale workflow
has already released the group. Same-head queued duplicates still retire on an
exact-head formal receipt. In-flight state remains diagnostic only and never
becomes review success.

## Cross-head admission follow-up (2026-09-20)

Exact `f3f6cc28f2a39e11d1a1e17036c639a13c4920a3` grouped the entire
workflow by target repository and pull request only. `queue: max` correctly
preserved same-head pending owners, but it also serialized different heads.
Under a long semantic review, a synchronize event therefore could not reach the
downstream PR-scoped `cancel-in-progress: true` group that retires stale model
work.

RED `1cf2d425342d73c851370dc433b6cab76037dc1d` requires the
workflow-level group to bind the exact `pr_head_sha`: same-head events render
the same key, different heads render different keys, and the downstream review
job remains PR-scoped with cancellation enabled. GREEN
`81f15bfffb088708eac808c4d0df80f69febdfb4` appends the payload head
SHA, using `github.run_id` only for malformed events without one. This preserves
same-head `queue: max` serialization while allowing a new head to validate and
reach the existing stale-review retirement boundary.

Exact `a33c0b4f0ddc0b2ba297cf3ce8cd3d775f55df87` verification passed
**14/14** focused policy assertions, YAML parse **2/2**, Python test compile
**2/2**, and extracted caller Bash syntax **1/1**. Full pytest is not claimed
because the isolated verifier does not provide pytest; hosted exact-head Checks
and an independent current-head review remain mandatory.

GitHub. (2026). *Control the concurrency of workflows and jobs*. Retrieved
September 20, 2026, from
https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency
