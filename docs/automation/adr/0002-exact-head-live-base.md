# ADR-0002 — Exact source-head plus independently resolved live-base evidence

Status: active_pr

## Context

A PR API base SHA can be a historical snapshot and does not necessarily represent the current protected base-ref tip. Reviews and checks may also refer to older heads.

## Alternatives

1. Trust PR metadata snapshots.
2. Track only source head.
3. Bind decisions to exact source head and independently resolve the current live base tip.

## Decision

Use option 3. Source revision and live base revision are separate evidence identities. Exact-head verification never transfers after a source-head change; base-sensitive acceptance is re-evaluated after material base movement.

## Consequences

More refetching is required, but stale-base and predecessor-evidence errors become explicit.

## Failure and recovery

If head/base/ref changes before mutation or merge, invalidate the affected decision and recompute from live state.

## Security and governance

Stale revision evidence cannot authorize source writes, approval sufficiency, or protected merge.

## Acceptance

Automation tests must include stale PR base metadata, moved heads, predecessor checks/reviews, and independently resolved base tips.

## Supersession

Supersede only if GitHub provides an equivalent atomic decision primitive that binds source, live target base, gates, and merge authority.
