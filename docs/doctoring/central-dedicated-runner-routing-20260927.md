# Central dedicated runner routing

## Status

Proposed workflow change; organization runner groups and five S1 runners are
already deployed. This document does not assert protected-main adoption.

## Context

The 2026-09-27T09:41:06.945544+00:00 collection recorded 610 unique queued central runs.
Trusted-main dispatch queues included 61 CodeQL and 31 OpenCode runs; three
control workflows had 18 main-branch runs. Older runs may be stale, so these
counts are allocation evidence, not exact-head merge evidence.

An exact-rational linear relaxation plus exhaustive integer allocation selected
one additional runner for each lane under a four-core host CPU-quota budget,
32 GiB additional guest RAM and 160 GiB sparse-disk budget. Existing two runners
were preserved. Historical successful job duration sums excluded queue waits.
The forecast is sensitive to service times; measured latency improvement remains
unverified. The detailed calculation is retained in the system-management task's
`central-runner-optimization-20260927.md` and JSON input/output receipts.

## Decision

Declare dedicated routing in the five workflow files:

| Workflow | Runner selection |
| --- | --- |
| CodeQL scan dispatch | Group `CWL central CodeQL`, labels `self-hosted`, `linux`, `x64` |
| OpenCode review dispatch | Group `CWL central OpenCode`, labels `self-hosted`, `linux`, `x64` |
| Agent mention router | Group `CWL central control`, labels `self-hosted`, `linux`, `x64` |
| Hourly review recovery | Group `CWL central control`, labels `self-hosted`, `linux`, `x64` |
| PR review merge scheduler | Central caller: self-hosted Linux X64 with `cwlab-control`; other callers: `ubuntu-24.04` |

Groups 4/5/6 allow only the central repository and their selected workflow paths
at `refs/heads/main`. Keep those restrictions and external contributor approval.
The control runner has the `cwlab-control` label. A reusable workflow inherits
the caller's repository context, so its consumer branch must retain hosted access.

The OpenCode guest exposes four virtual CPUs and 20 GiB RAM to satisfy the
existing four-CPU/14-GiB Docker sandbox, with host CPUQuota 100%. CodeQL has two
CPUs/eight GiB; control has one CPU/four GiB. Existing guests remain running;
their group excludes future OpenCode dispatch because their three visible CPUs
cannot satisfy that Docker request. A real container resource check passed on
the new OpenCode guest. Do not change model deadlines, providers, permissions,
concurrency, or protected review requirements to compensate for admission delay.

## Consequences and alternatives

Explicit selectors keep long reviews separate from short control work. Native
organization group restrictions remain the trust boundary. A missing dedicated
runner now queues the central job instead of silently choosing a hosted runner.

Generic Ubuntu labels alone served existing queued jobs, but did not express
durable lane selection in source. Expanding central groups to every consumer
repository would weaken their access boundary; caller-aware scheduler routing
avoids that expansion. No new manual dispatch trigger or PR-branch group access
is added.

## Verification

Check workflow syntax, runner-selection contracts, the independent OpenCode
workflow blob pin, and existing affected contracts. Native assignment receipts
already show CodeQL dispatch and OpenCode review execution on the new runners
and a successful control queue job; they do not prove this proposed source has
landed or that all required review gates pass.


## Noema control admission follow-up

At 2026-09-27 10:38 UTC the organization API listed five online runners,
while the central repository still listed 455 queued runs. Group 6's control
runner was idle in the subsequent group-membership observation; these are
point-in-time observations, not a measured capacity forecast.

Noema's admission, changed-scope, closed-run cleanup, and post-failure
re-dispatch jobs now select `self-hosted`, `Linux`, `X64`, `cwlab-control`
only in the central repository. Consumer repositories retain Ubuntu 24.04.
The Noema model-review job retains Ubuntu 24.04: this change allocates short
control work and does not assert compatibility of a model sandbox with the
one-core/four-GiB control guest.

Deployment requires group 6's existing trusted-main workflow allowlist to
include `ContextualWisdomLab/.github/.github/workflows/noema-review.yml@refs/heads/main`.
Preserve every existing allowlist entry, repository restriction, and external
contributor approval. Do not allow a feature-branch ref. Until that grant is
verified, the source change is not an operational routing repair.
