# Doctoring record: OpenCode exact-head dispatch audit (2026-09-17)

- **Date:** 2026-09-17
- **Subject:** Snapshot of an exact-head OpenCode Review Dispatch audit over open
  `ContextualWisdomLab/.github` pull requests after the coalesce gap, captured in
  `/tmp/docs-review-dispatch.json`.
- **Decision record:** none — audit trail only; no workflow or scheduler change.
- **Source artifact:** `/tmp/docs-review-dispatch.json`
  (`generated_at=2026-09-17T21:19:25.528137+00:00`,
  `event_type=opencode-review`, `coalesce_flag_touched=false`).

## Counts

| Outcome | Count |
|---|---|
| Dispatched | **2** |
| Skipped | **11** |
| Errors | **0** |
| Unconfirmed | 0 |
| Total PRs audited | 13 |

## Redispatched (exact-head missing)

| PR | Head SHA | Dispatch run | Dispatched at (UTC) |
|---|---|---|---|
| ContextualWisdomLab/.github#2215 | `ab04bfdb3cbd69cc7ef90dc6bb2104b88550b89c` | [35275996814](https://github.com/ContextualWisdomLab/.github/actions/runs/35275996814) | 2026-09-17T21:19:14Z |
| ContextualWisdomLab/.github#2226 | `ff16764ac374b23be2d8131a5d03c89d62cd0bc7` | [35275997215](https://github.com/ContextualWisdomLab/.github/actions/runs/35275997215) | 2026-09-17T21:19:17Z |

## Skipped (exact-head dispatch already exists)

All eleven skips used reason `exact-head dispatch already exists`:

`#2249`, `#2250`, `#2251`, `#2252`, `#2253`, `#2254`, `#2166`, `#2170`,
`#2174`, `#2184`, `#2205`.

## Reading

Exact-head deduplication held for the majority of the open set: eleven PRs
already had a queued or pending OpenCode Review Dispatch bound to their live
head SHA. Only `#2215` and `#2226` lacked that binding and were redispatched.
Zero errors and zero unconfirmed results — the audit completed cleanly.
