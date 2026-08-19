# Agent mention sweep rate-limit fail-fast boundary

Updated: 2026-08-15

## Incident

Scheduled `Review Agent Mention Router` run `31868885733` exhausted the OpenCode GitHub App installation REST budget before processing the requested review queue. The sweep continued traversing repositories after the first installation-wide `API rate limit exceeded` response and finished with zero dispatches plus 116 isolated failures. Repeating requests after the shared budget is exhausted cannot recover candidate-local work and consumes runner time while obscuring the single control-plane cause.

## Decision

Treat explicit GitHub primary- or secondary-rate-limit messages as **sweep-global capacity exhaustion**, not candidate-local failures. The sweep records the first failed scope, then raises `SweepRateLimitExhausted` immediately. Ordinary repository, pull-request, review, acknowledgement, and dispatch failures remain isolated exactly as before.

This change is intentionally narrow. It does not retry, sleep, change credentials, widen permissions, alter the canonical invocation key, modify the exact-name artifact ledger, or claim that a failed request was dispatched. A later scheduled invocation may run after GitHub restores capacity. Interactive/local routing and the separate concurrency-isolation repair remain independent control-plane lanes.

The scheduled CLI emits an error with the budget-reset action and exits 1, so
operators see a bounded failure rather than an unhandled traceback.

## Why fail-fast

GitHub documents that installation access tokens share an installation-level primary REST budget. When a primary limit is exceeded, requests return HTTP 403 or 429 and callers should not retry until the reset time. GitHub also states that integrations should stop and wait on secondary-rate-limit responses; continuing to make requests while rate-limited may lead to integration bans. The current sweep cannot safely infer reset headers from the `gh` exception string, so the bounded action is to stop the current scheduled traversal rather than amplify the exhausted state.

## Verification contract

- a synthetic installation-wide primary-limit error on the first PR aborts before the second PR is touched;
- exactly one failure is recorded for the first exhausted scope;
- secondary-rate-limit messages are classified as sweep-global exhaustion;
- unrelated authorization/resource errors remain candidate-local and preserve existing failure isolation;
- the permanent agent-mention quality suite continues to require 100% owned production statement/branch and public docstring coverage.

## Rollback

Revert `SweepRateLimitExhausted`, `is_rate_limit_exhaustion`, and their focused regression if GitHub changes the CLI error contract or the router gains structured response-header handling. Do not restore repeated API calls after a proven shared rate-limit exhaustion without an equivalent bounded backoff/stop mechanism.

## References

GitHub. (n.d.). *Rate limits for the REST API*. GitHub Docs. Retrieved August 15, 2026, from https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api

GitHub. (n.d.). *Rate limits for GitHub Apps*. GitHub Docs. Retrieved August 15, 2026, from https://docs.github.com/en/apps/creating-github-apps/registering-a-github-app/rate-limits-for-github-apps
