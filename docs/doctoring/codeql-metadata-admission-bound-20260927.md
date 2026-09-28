# CodeQL metadata job admission bound

On 2026-09-27, central Strix admission job108624881622 was queued with the
correct self-hosted/cwlab-control labels while all three control runners were
busy. Contextual-orchestrator CodeQL job108620193038 occupied cwlab-s2-01 in
`Read current-head CodeQL dispatch verdict`. This establishes a shared control
lane and live metadata work; it does not prove which individual API call stalled.

The central codeql-pr jobs detect languages, read verdicts, or coordinate
dispatch, with no job execution bound. Language detection checks out source
for trusted classification; it does not execute PR-authored code. A stalled gh call can
therefore occupy a control slot for the platform default six hours. Add the
existing operational budgets: five minutes for detection/dispatch and ten
minutes for verdict reads, as used by control cleanup.
The separately dispatched scan and model inference keep their own contracts;
no elapsed inference time becomes a model-failure verdict. A timed-out metadata
job remains non-passing and cannot authorize a merge.

The new assertion fails against unchanged source. The CodeQL and runner
contracts pass in local and GITHUB_ACTIONS=true modes (36 each); actionlint
and whitespace checks pass. Runner access, source-ref guards, permissions,
head revalidation, concurrency and authenticated verdict checks are unchanged.
Existing runs retain their original source and were not cancelled. Native
post-merge execution is needed to prove slot recovery and queue latency.

## Terminal and idle-runner revalidation

At 2026-09-27 14:46 UTC, job108620193038 was verified terminal: started
13:16:43, completed 13:23:14, failure. Its verdict-read step succeeded from
13:16:48 to 13:23:06 (378 seconds), then its enforcement step failed. It is
not a currently stuck slot, nor proof of a particular stalled API call. The
initial five-minute proposal would interrupt this observed orderly path;
only the verdict-reader budget is therefore revised to the existing ten-minute
control budget. This is an operational bound, not a calibrated latency optimum.

Strix job108624881622 remains queued with cwlab-control labels while group6
reports an online idle cwlab-s1-05. Its run36321072667 has no pending deployment
approval. The selected-workflow allowlist includes trusted-main Strix. This
contradicts treating every wait as simply all control runners being busy;
workflow eligibility, concurrency and organization admission still require
current evidence. These observations do not authorize cancellation or runner
access expansion. Some REST reads succeed while run-list reads return quota
errors, so no complete active-job census or current global-ceiling claim is made.

## Current-main integration, 2026-09-28

Replayed only the three job budgets onto central main `5b0024a9`.
Existing trusted-source routing, current-head validation and scan contracts remain.
The CodeQL workflow, runner-image and required-queue contract suites pass:
112 tests locally and 112 with `GITHUB_ACTIONS=true`. Actionlint (ShellCheck
disabled) and `git diff --check` pass. These checks establish local source
contracts; native queue recovery remains unverified. Earlier runner observations
above are historical and do not describe current occupancy.
