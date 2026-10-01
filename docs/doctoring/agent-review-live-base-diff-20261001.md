# Agent review live-base diff RCA

Status: Proposed shared-workflow repair; hosted exact-head evidence and
independent review remain mandatory.

## Failure evidence

Draft `.github#1678` exact head
`b9651115be28f9dd46f8b93a2a753b2652c57970` failed Agent Review Runtime
Quality CI run `36804488453`, job `110185716853`, step `Verify consolidated
workflow contract`. All preceding contract suites succeeded. The terminal
`git diff --check` used event base `f250638827f8252b0d9e5cb2601f4d333f96162f`
and reported 407 whitespace violations across four files.

## Root cause and boundary

The PR head already contains protected `main@37b10243cec3d160ecc9c1be75c71428b160a703`
as an ancestor through ordinary owner integration. The pull-request event still
carried its older base SHA, so the workflow treated intervening protected-main
history as the PR delta. The four files are clean relative to the live base;
rewriting their historical contents in the consumer would hide the workflow
identity defect and duplicate the `.github` control-plane responsibility.

## Repair and verification

The changed-path selector and terminal whitespace gate refetch the exact base
ref immediately before computing its merge-base with the exact head. This
closes the second stale window where the base could advance during a long
quality job after checkout but before the terminal whitespace gate. The head
checkout assertion remains exact, and a failed fetch or missing merge-base
fails closed.

The original regression contract was changed first and failed in two cases
against the event-SHA implementation. A follow-up RED contract then failed
because neither merge-base decision refetched the base; the minimal repair adds
one fail-closed fetch at each decision. After the workflow repair, 36 focused
consolidation, single-runner, autofix-context, and runtime-budget tests pass.
Applying the same command to the real #1678 graph resolves the live change base to
`37b10243cec3d160ecc9c1be75c71428b160a703`; `git diff --check` succeeds.

Completion requires a dedicated owner PR, exact-current-head hosted Checks,
qualifying independent review, ordinary protected-main integration, ordinary
merge of the owner into #1678, and a fresh successful #1678 run. Pending,
queued, skipped, or predecessor results are not passing evidence.

## Canonical owner integration and stacked admission

Before dependent exact-head revalidation, the repair ordinary-merges canonical
parser/security/coverage owner
`.github#2530@dc54310c8c5ee6637274e7e82f5ea53d64ad91e6`. The resulting owner PR head
`b66036e3702b95d47fc7eac5eb6097e198d49997` is an ordinary two-parent merge,
but it produced no Agent Review Runtime Quality run: the workflow's
`pull_request` trigger still admitted only base `main`, while this PR now
targets the canonical owner branch.

The regression contract failed against that filter. The minimal repair removes
only the pull-request base restriction and retains path selection, read-only
permissions, exact-head checkout, and PR-stable concurrency. This permits the
owner workflow to produce exact-head evidence on canonical stacked bases; it
does not make a pending or skipped result passing evidence.

The merge preserves both lineages without force or rebase and keeps dependency
repair in the canonical owner. The resulting head must rerun all Checks;
predecessor success is causal evidence only, not admission evidence.
