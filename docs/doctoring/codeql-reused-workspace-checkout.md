# CodeQL checkout on reused runner workspaces

## Evidence

On 2026-09-27 the new dedicated CodeQL runner was online and received real
jobs. Job `108598782912` in run `36298665661` failed during materialization
with exit code 3; two other jobs on that runner failed at the same step.
The parent runs still had queued work, so their complete logs were unavailable.
The annotations prove the failure stage and exit code, not its exact command.

The shared materialization script ran `git init` followed by unconditional
`git remote add origin`. Git initialization preserves an existing remote.
A real isolated Git reproduction with a retained origin returns exit code 3
and `error: remote origin already exists.` This is a demonstrated source
regression on reused workspaces; attribution of the observed job to that
specific command remains an inference until its log becomes available.

## Repair

Reuse the repository's pinned `actions/checkout` v7 action. It receives the
independently validated target repository and exact head SHA, cleans retained
workspace state, and does not retain the checkout credential. Existing token
selection, live metadata validation, scan permissions, and security gates remain
in force. This also avoids accumulating global Git authentication configuration.

The separate status-publication 403 annotations do not prove checkout failed
for permission reasons and are not repaired or treated as success by this change.
Dedicated runner routing remains owned by PR #2416.

## Verification

The real Git reproduction establishes the existing-origin failure. The workflow
contract checks the pinned native action, exact target/head inputs, cleanup and
credential removal. Workflow syntax validation and the required full quality
gate are also run. Hosted checkout and scan success still require a current-head
job receipt; local contracts alone do not establish either.
