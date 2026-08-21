# Auto-rebase GraphQL REST fallback

## Incident and buyer impact

The merge scheduler (`ContextualWisdomLab/.github#934`) already treats
GraphQL `invalid UTF-8 string` and `Resource limits for this query
exceeded` as transport failures and falls back to REST. The auto-rebase
scheduler still listed open pull requests through GraphQL only. The same
Unicode branch names and the live 58-plus-PR org queue therefore aborted
DIRTY-head repair before any rebase ran.

A buyer paying for the org control plane then sees stale conflicted
heads that never catch up to `main`, even though the unique rebase
repair already exists.

## Decision

Classify those two GraphQL markers, plus the shared transient GitHub API
family, as transport/capacity failures in `pr_auto_rebase`. Retry is
owned by `gh_graphql`; when it still raises, list pull requests through
REST, refresh `unknown` `mergeable_state` with one GET, and load the
head commit so the human-activity window still applies. GraphQL schema
errors stay fail-closed. A REST 403 is not retried or paginated away.

Do not copy `pr_review_merge_scheduler.rest_pr_node`: that mapper pulls
reviews, checks, and files the rebase scheduler does not consume.

## References

Yergeau, F. (2003). *UTF-8, a transformation format of ISO 10646*
(RFC 3629). Internet Engineering Task Force.
https://doi.org/10.17487/RFC3629

GitHub. (2025). *Using the GitHub GraphQL API*.
https://docs.github.com/en/graphql

GitHub. (2025). *Rate limits and node limits for the GraphQL API*.
https://docs.github.com/en/graphql/overview/rate-limits-and-node-limits-for-the-graphql-api

Fielding, R., Nottingham, M., & Reschke, J. (2022). *HTTP semantics*
(RFC 9110). Internet Engineering Task Force.
https://doi.org/10.17487/RFC9110
