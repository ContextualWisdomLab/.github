# Noema exact-head review submission is revalidated at the write boundary

검토 기준일: **2026-09-07**

## Problem

GitHub Actions concurrency cancellation is best-effort. A run already executing
model work can reach the review POST after another run has published a valid
Noema review for the same head. Head equality alone does not prove that the
write is still unique.

## Decision

The Noema gate keeps the pre-model duplicate check, then re-fetches the live
pull request after model work. Immediately before `submit_review`, it repeats
the trusted exact-head Noema receipt check. A concurrent receipt returns
successfully without publishing a duplicate. Closed or moved heads continue to
fail closed before this check.

The unused `statusCheckRollup` selection is removed because review publication
does not consume check contexts.

## Verification contract

`test_inspect_and_review_rechecks_for_a_concurrent_submission_before_posting`
models two live reads: the first has no receipt and the second contains a
trusted receipt for the same head. The POST recorder must remain empty. Hosted
exact-head checks remain mandatory.

## Status

**Proposed** in ContextualWisdomLab/.github#1482. Protected `main` remains the
release authority.

## Reference

GitHub. (n.d.). *Control the concurrency of workflows and jobs*. GitHub Docs.
Retrieved September 7, 2026, from
https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency
