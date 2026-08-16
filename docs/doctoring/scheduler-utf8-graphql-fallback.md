# Scheduler UTF-8 GraphQL fallback

## Incident and buyer impact

The merge scheduler aborted while listing pull requests because `gh api
graphql` returned `invalid UTF-8 string`. That marker was not treated as
transient, so the existing REST fallback never ran. Unicode branch names
and comment bodies then blocked the entire org queue.

## Decision

Treat `invalid UTF-8 string` and `Resource limits for this query
exceeded` as transport/capacity failures, not schema or authorization
errors. Retry and fall back to REST. Do not treat GraphQL field errors
or `Resource not accessible by integration` as transient. This keeps
operational Unicode content and the full open-PR queue available
instead of masking or dropping them.

## References

Yergeau, F. (2003). *UTF-8, a transformation format of ISO 10646*
(RFC 3629). Internet Engineering Task Force.
https://doi.org/10.17487/RFC3629

GitHub. (2025). *Using the GitHub GraphQL API*.
https://docs.github.com/en/graphql

GitHub. (2025). *Rate limits and node limits for the GraphQL API*.
https://docs.github.com/en/graphql/overview/rate-limits-and-node-limits-for-the-graphql-api
