# Central review handoff and runner repair

## Scope

This change repairs existing review control paths. It does not claim that the
organization's hosted workload migration, LiteLLM onboarding, or product
validation is complete.

- Central Noema handoff/base binding is already owned by
  ContextualWisdomLab/.github#2111. A duplicate implementation was removed
  from this change; this patch does not claim that repair is deployed.
- OpenCode's immediate post-approval scheduler invocation is dry-run,
  merge-disabled, auto-merge-disabled, and branch-update-disabled. A formal
  review is evidence, not permission for that job to mutate the reviewed PR.
- The coalescing tick is a trusted central-main schedule with no PR checkout.
  It selects the already-admitted `CWL MCP remediation` group with
  `self-hosted`, `linux`, and `x64` labels. The existing job-level enable flag
  still prevents inert ticks from obtaining a runner.
- The coalescing invocation explicitly selects `--merge-mode disabled` as
  well as disabling auto-merge and branch updates. Disabling auto-merge alone
  does not disable a direct-merge mode.

The regular review-event and scheduled merge scheduler paths are unchanged.
This patch does not establish an end-to-end no-merge guarantee for a PR that
those separately authorized paths inspect.

## Current operational evidence

GitHub check-run annotations for
`ContextualWisdomLab/psychometrics-commons#165`, head
`bb9028714d996871ed2588ea9a3aa83fd581af84`, reported that the hosted job could
not start because the account was locked due to a billing issue. The jobs
had runner id `0` and no executed steps. They are not executed test failures.

The product fix was previously verified locally, including branch coverage
1724/1724. That evidence does not replace GitHub required checks, independent
review, or an admitted isolated self-hosted build lane.

An organization runner-group readback showed `CWL MCP remediation` already
admitted the coalescing workflow at central `refs/heads/main`, with two online
runners. Runtime availability is re-read before dispatch; this observation is
not a permanent capacity claim.

## Remaining prerequisites

- Product PR execution must use a verified isolation boundary; do not send
  untrusted builds to shared metadata/review runners.
- A Noema approval is not yet accepted by the scheduler's blanket bot
  exclusion. A future change must recognize only authenticated authorized
  App evidence on the exact head, preserve revocations, and not admit arbitrary
  bot approvals.
- Current review configuration remains `orchestrator/free`; it is not a
  literal `auto` model setting. An authenticated LiteLLM onboarding and
  explicit gateway contract/policy update are required before claiming the
  requested `auto` route.
- The public LiteLLM schema at `https://litellm.poinnetworks.net/openapi.json`
  declares authentication for `/key/generate`; no unauthenticated key was
  requested or issued. A dedicated inference credential must enter the
  gateway's approved secret boundary, not source, logs, or review text.
- No hosted security or product-validation workflow was disabled by this
  patch. Mandatory unavailable evidence stays non-passing until an equivalent
  isolated replacement is verified.

## Verification

Regression tests enforce assessment-only post-publication scheduler arguments
and pin the trusted coalescer's runner selection. Workflow shell syntax and
actionlint validate the modified callers. Two pre-existing CodeQL tests now
freeze their default-clock input so September fixtures do not expire under
October's real wall clock; production freshness thresholds are unchanged.

## References

- GitHub. (n.d.). *Secure use reference*.
  https://docs.github.com/en/actions/reference/security/secure-use
- GitHub. (n.d.). *Events that trigger workflows*.
  https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows
- LiteLLM. (n.d.). *Self serve*.
  https://docs.litellm.ai/docs/proxy/self_serve
