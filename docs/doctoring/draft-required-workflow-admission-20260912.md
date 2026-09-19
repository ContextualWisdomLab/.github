# Draft required-workflow admission

## Problem and exact evidence

Pull request #2106 head `24bb6591ab7df23558cb793b4af60c567ff9da97`
generated Security Scan `34688578677`, CodeQL PR `34688578675`, SAST
`34688578674`, Python Security `34688578683`, and Runtime Quality
`34688578679` while the pull request was Draft. Restoring Ready at the same
head generated a second set. The first four runs were cancelled after queued
jobs had already entered admission; Runtime Quality had already consumed a
runner and completed. This is same-head lifecycle queue waste, not stale source
or a test failure.

The first successor canary exposed two independent omissions. Security Scan
skipped its `changed-scope` path but admitted independent Gitleaks job
`103542086113`. After that guard was repaired, Ready restoration generated four
security workflows but no Runtime Quality run because that workflow relied on
the default `pull_request` activity set, which excludes `ready_for_review`.
Current-head review then found that sandbox evidence paths started Runtime
Quality without selecting or executing a sandbox contract suite. RED
`3648b848` requires non-vacuous selection and GREEN `d1473882` adds the
100% branch-coverage/public-doc gate plus queue-contract execution. A second
RED `b6715554` proves the selector test's literal `\\n` split retained the
entire workflow; GREEN `2c00900e` restricts assertions to the actual trigger
block.

The 2026-09-20 stacked canary reproduced a fourth omission. Exact head
`5bd73bef20010ea020ab1912ce9564cea8f4ffb5` targeted the canonical Strix owner
branch and changed all five required workflow paths. Its Ready transition
created Security Scan `35476467884`, SAST `35476467914`, and CodeQL
`35476467908`, but no Runtime Quality or Python Security generation. Both
missing workflows restricted `pull_request.branches` to default-like names;
the three working workflows intentionally accepted every PR base.

## Constraints and selected repair

The workflows must keep `ready_for_review`, PR-keyed concurrency, and their
existing close-event behavior. Security workflows that also run on push,
schedule, or `repository_dispatch` must not lose those non-PR paths. Trigger
filters alone are insufficient for organization required workflows, so the
repair uses the existing job-level policy boundary:

- pull-request-only workflows require `pull_request.draft == false` on every
  independent entry job, including both Security Scan `changed-scope` and its
  document-sensitive `gitleaks` gate;
- mixed-event workflows allow every non-PR event and require non-Draft state
  only for pull-request events;
- downstream jobs remain unchanged and naturally skip through `needs` when the
  admission job skips.
- Runtime Quality explicitly subscribes to `ready_for_review`, so its Draft
  skip cannot strand the exact head when review admission opens.
- Runtime Quality and Python Security do not restrict pull-request base names;
  stacked owner branches receive the same Ready admission as default branches.
- Sandbox verifier changes select a dedicated suite with 100% branch coverage,
  100% public documentation, compilation, and the queue selector contract.
- Trigger-path assertions exclude the workflow `jobs` block, preventing a
  matching path elsewhere from satisfying admission tests.

No new workflow, dependency, scheduler, token, or status context is added.

## Alternatives rejected

- Removing `ready_for_review` would strand Draft-origin PRs without fresh
  evidence when they become reviewable.
- Adding head SHA to concurrency would not prevent the same-head lifecycle
  duplication and would weaken close-event cancellation.
- Cancelling the duplicate later still spends queue admission and runner time.
- Enumerating current owner branch names would require mutable central policy
  for every future stack; omitting the pull-request base filter is the existing
  Security Scan, SAST, and CodeQL contract and keeps push branch filters intact.

## Verification and follow-up

`tests/test_required_workflow_queue_contract.py` binds all five workflows and
all independent entry-job guards while preserving the existing close-event
contract, requiring Runtime Quality Ready admission on default and stacked
bases, executing sandbox evidence contracts, and limiting trigger assertions
to the actual trigger block. The proposal is not
complete until exact-head hosted Checks and independent review pass, it merges
through ordinary protection, and a post-merge Draft→Ready canary shows skipped
Draft jobs followed by one fresh Ready generation.
