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
only in the central repository. The concurrent #2421 allocation for contextual-orchestrator consumers is preserved; other consumer repositories retain Ubuntu 24.04.
The concurrent #2421 model-review allocation to the MCP remediation pool is preserved; this change allocates short
control work and does not assert compatibility of a model sandbox with the
one-core/four-GiB control guest.

Deployment requires group 6's existing trusted-main workflow allowlist to
include `ContextualWisdomLab/.github/.github/workflows/noema-review.yml@refs/heads/main`.
Preserve every existing allowlist entry, repository restriction, and external
contributor approval. Do not allow a feature-branch ref. Until that grant is
verified, the source change is not an operational routing repair.


## Issue 1565 review admission follow-up

The SDK and naruon consumer Noema jobs still selected hosted Ubuntu after the
initial runner rollout. Extend the existing repository allowlist to
`ContextualWisdomLab/cwl-telemetry` and `ContextualWisdomLab/naruon`, only when
`github.workflow_ref` is exactly the central Noema workflow at `refs/heads/main`.
Metadata and continuation use the control pool; model review uses MCP remediation.
PR-authored workflow refs retain hosted execution and existing fork admission,
credentials, review publication, concurrency and inference-time policy remain.

At 2026-09-27 12:12 UTC, group 3 repository membership was verified after two
repository-specific PUT requests. Its selected-workflow restrictions remain;
group 6 already allows repositories subject to its selected-workflow restrictions.
This is runner admission, not approval or evidence of a completed model review.
Existing queued runs retain their original workflow revision and may still wait
until event-driven current-head recovery creates a new run.

The allocation calculation from the initial rollout is reused; no new host
capacity or independent service-time measurement justifies another solver.
The routing regression fails against the unchanged baseline. Workflow syntax
and affected contracts passed: 238 passed, 2 skipped with `GITHUB_ACTIONS=true`;
`actionlint` and `git diff --check` passed.


## fast-mlsirm Strix control admission

Current fast-mlsirm PR #2220 head `4eaeb799a6647ea29f3f4902d9ca79a1377e795c`
queued Strix admission job `108617323217` with `ubuntu-24.04`, despite the
self-hosted rollout. Route only changed-scope, current-head admission,
superseded-run cleanup and manual status publication through group 6 when
the source is exactly central `strix.yml@refs/heads/main` and the caller is
the central repository or fast-mlsirm. These jobs do not check out PR code.
The model scan keeps its existing hosted image and all evidence, credentials,
fork handling and live-head validation remain intact.

Reuse the deployed allocation; no new service-time or capacity measurement
justifies a different solver result. Deployment requires adding only central
`strix.yml@refs/heads/main` to group 6's selected workflows, preserving all
existing restrictions and grants. Old queued jobs keep their original source.

The routing test failed on the unmodified workflow. The affected runner,
changed-scope and dependency-hash tests passed (21 tests); actionlint and
diff whitespace checks passed. This is local source proof, not completed
consumer gate evidence.

## Naruon Strix metadata admission follow-up

At 2026-09-27 12:59 UTC, current Naruon #1789 head
`8b7e3d03236073191e4945c03eed18d02471c336` had Strix run `36320590274`
queued with admission, changed-scope and cleanup jobs reporting `runner_id=0`
and `ubuntu-24.04`. Group 6 had online idle `cwlab-s1-01` and `cwlab-s1-05`.
Naruon #1800 Semgrep had obtained a hosted runner and succeeded, so this does
not establish an organization-wide hosted outage or its underlying capacity cause.

The deployed Strix metadata expression admitted only `.github` and `fast-mlsirm`
to control runners. Add Naruon to that same bounded caller list, retaining exact
central `strix.yml@refs/heads/main`, group 6 and `cwlab-control` guards. All four
metadata jobs use API calls without checking out PR code; the model scan stays
on its existing hosted image. Reuse the existing allocation rather than changing
model timing, providers or security gates.

The live group 6 response now reports visibility `all`, restricted workflows
including central Strix at `refs/heads/main`, and public repositories allowed.
This updates the earlier deployment snapshot above; this change neither edits
runner-group grants nor assumes arbitrary consumer workflows can access them.
Existing queued runs retain their original workflow revision. Source tests prove
selection intent only; post-merge native assignment and end-to-end gate evidence
are still required before claiming queue recovery.

The added Naruon routing assertion fails against the unchanged workflow and
passes with this delta. Focused runner and scope contracts pass in both local
and `GITHUB_ACTIONS=true` modes (13 each); actionlint and whitespace checks pass.
