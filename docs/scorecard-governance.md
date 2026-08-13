# Scorecard Governance Runbook

This repository owns the central required workflows used by
ContextualWisdomLab repositories. Scorecard Medium-or-higher governance findings
are handled as repository settings or central workflow controls, not
as per-repository suppressions.

## BranchProtectionID

The default branch must have both a GitHub branch protection rule and the
organization required-workflow ruleset. The branch protection rule for `main`
or the inherited organization ruleset must require all of the following:

- status checks from the central review, SAST, dependency, and Scorecard gates
  to pass against the latest head commit before merge;
- stale approvals to be dismissed after a push;
- current-head OpenCode review evidence from the central required workflow;
- code owner review coverage through CODEOWNERS-owned workflow and CI paths,
  with the organization required-workflow ruleset carrying the enforceable
  single-maintainer approval gate;
- review thread resolution before merge;
- last-pusher approval protection;
- force-push and branch deletion protection.

The organization required-workflow ruleset remains the distribution layer for
other repositories. The branch protection rule is kept as the repository-local
signal that OpenSSF Scorecard can evaluate directly.

## MaintainedID

`MaintainedID` is age based for this repository until the first 90 days have
elapsed from its 2026-06-19 creation date. It is not a vulnerability finding.
Until the age window closes, each Scorecard run is reviewed alongside current
pull-request checks, code scanning alerts, and central workflow failures.

## SASTID

`SASTID` is enforced for new commits through the central CodeQL, Strix, Trivy,
OSV, dependency-review, and Scorecard workflows. Historical commits that
predate those workflows cannot be rescanned into an already-completed check
history, so the durable control is to keep the current-head workflows required
and to cancel superseded runs.

## CodeReviewID

`CodeReviewID` is a review-governance signal. The durable control is
current-head OpenCode approval evidence, stale-approval dismissal,
review-thread resolution, and latest-head required checks. Historical
approved-changeset ratios are monitored but not used to waive current-head
review gates.

## Token-Permissions

Top-level or job-level `contents: write` on a one-shot repair workflow
is a Scorecard Token-Permissions score-0 finding. Temporary branch
writers that only rewrite comments or version strings are not merge
evidence. Apply those edits in the pull-request tree and delete the
writer. Keep `contents: write` only on the documented dispatch and
scheduler exception paths in
[`docs/automation/review-agent-comment-invocation.md`](automation/review-agent-comment-invocation.md).
Pinned action comments must name the release the SHA embeds so a
buyer can audit which scanner ran.

## Failure Evidence

Every central workflow failure must print the actionable reason in its logs.
Vulnerability gates print the package, advisory or CVE, affected manifest, and
severity when available. Review gates print whether the block came from
current-head checks, unresolved review threads, stale approvals, mergeability,
or GitHub Actions requiring manual approval.
