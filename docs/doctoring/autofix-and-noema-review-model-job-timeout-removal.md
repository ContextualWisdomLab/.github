# Removing job-level timeout-minutes from autofix and noema-review

> Superseded on 2026-09-05: synchronous central model execution now has a
> 900-second bound so a stalled provider cannot retain a shared runner.

## What was wrong

Earlier the same day, `pr-review-autofix.yml`'s `autofix` job (#1714) and
`noema-review.yml`'s `noema-review` job (#1715) each received a job-level
`timeout-minutes` (25 and 210 respectively) as part of fixing a real,
separate problem: several central `.github` workflow jobs had **no**
`timeout-minutes` at all, so a genuinely stuck job (a hung transport, a
runner fault) could occupy a shared runner for up to GitHub's 360-minute
platform default, contributing to the org-wide Actions capacity incident
documented elsewhere in `docs/product-technical-gap-baseline.md`.

That fix was correct for jobs whose steps do bookkeeping (cancel stale runs,
publish a status) or that poll for a verdict a *separate* process prepares
(`opencode-review.yml`'s `poll_deadline_epoch`, which bounds a step polling
GitHub for whether a repository-dispatch-triggered review process has posted
a receipt yet -- the model call itself happens in a different workflow,
`opencode-review-dispatch.yml`, which correctly stayed unbounded).

It was **wrong** for `autofix` and `noema-review`, because in both of those
jobs the model call itself runs synchronously, in-job:

- `autofix`'s "Run OpenCode review autofix" step runs `opencode run "$(cat
  "$prompt_file")" ...` directly and blocks on its output (and a second
  `opencode run` for base-merge conflict resolution, later in the same job).
- `noema-review`'s "Prepare Noema model verdict" step runs
  `python3 .github/actions/noema-review/two_phase.py ...`, which itself
  calls the model (`NOEMA_LLM_API_URL`, `NOEMA_LLM_MODEL=orchestrator/free`)
  and blocks until it returns.

A job-level `timeout-minutes` on either job does not merely bound "how long
this job waits for something external" -- it bounds the model's own
reasoning/tool-use time directly, because the model call is the job's
dominant, synchronous body. That is exactly the fixed inference-time cap
`docs/product-goal-directive.md` #8 prohibits: "Model timeout은
application·Agent·Gateway 공통 상한 없이 기본 null이다" (no common upper bound
across the application/agent/gateway stack; defaults to null), and "정확성을
우선하고 OpenCode·Strix·Noema의 모델당 2시간 이상을 수용한다" (prioritize
accuracy; accommodate over two hours per model for OpenCode/Strix/Noema --
"over two hours" describes a floor on tolerance, not a ceiling to round up
to and hard-code).

Both original PR descriptions and in-file comments justified the added
timeouts by analogy to `opencode-review.yml`'s `poll_deadline_epoch` fix
(#1707) -- e.g. "gives that step the same ~180-minute allowance PR #1707 set
for its analogous model-wait deadline." That analogy was the actual mistake:
`poll_deadline_epoch` bounds a step that polls for a verdict a *different,
separately triggered* process prepares (an async external wait with no
model call in the bounded step itself); `autofix`'s and `noema-review`'s
jobs are not analogous, because their bounded step **is** the model call.

## What changed

- `.github/workflows/pr-review-autofix.yml`: removed `timeout-minutes: 25`
  from the `autofix` job. No replacement bound -- the job has no other
  timeout mechanism, matching the policy's "기본 null" default.
- `.github/workflows/noema-review.yml`: removed `timeout-minutes: 210` from
  the `noema-review` job. `cancel-closed-pr-runs` (pure GitHub API
  bookkeeping, no model call) keeps its unrelated `timeout-minutes: 20`.
- `tests/test_pr_review_autofix_writer_security_contract.py`:
  `test_autofix_job_has_a_bounded_runtime` (asserted a timeout WAS present,
  5-60 minutes) replaced with `test_autofix_job_has_no_job_level_timeout`
  (asserts one is absent).
- `tests/test_noema_orchestrator_workflow_contract.py`:
  `test_noema_review_job_has_a_bounded_runtime_above_the_two_hour_model_allowance`
  (asserted a timeout WAS present, 120-360 minutes) replaced with
  `test_noema_review_job_has_no_job_level_timeout` (asserts one is absent).
  `test_cancel_closed_pr_runs_has_a_bounded_runtime` is untouched -- that
  job has no model call, so its bound is correct as-is.

## Why this was caught, and what stayed the same

Devin's automated review on `ContextualWisdomLab/.github#1661` flagged a
leftover debris file, `scripts/ci/source_fix_pr1715_no_model_job_timeout.py`
-- part of this org's own autonomous self-repair loop, which had correctly
identified this exact bug and was in the middle of fixing it when its
generated PR was reconciled away as apparent "already-served-its-purpose
debris" without checking whether its fix had actually landed. It had not.
This doctoring entry and the accompanying fix restore, by hand (per this
org's "land it as a normal direct fix, not another self-modifying generator
script" convention), the fix that debris script was attempting.

`opencode-review.yml`'s `poll_deadline_epoch` (#1707), `pr-review-merge-scheduler.yml`'s
`scan-pr-queue` timeout (#1702), and `strix.yml`'s `cancel-superseded-pr-runs`
/ `publish-manual-pr-evidence-status` timeouts (#1713) were all re-checked
against the same question -- "does the bounded job's own step body run the
model synchronously, or does it wait on a separate async actor / do pure
bookkeeping?" -- and confirmed sound: none of them bound a step that itself
runs a model call. `strix.yml`'s main `strix` job (which does run the model)
correctly remains unbounded, as before.
