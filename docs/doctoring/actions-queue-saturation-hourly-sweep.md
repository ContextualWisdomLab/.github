# Actions queue saturation: hourly organization sweep

**Status:** HISTORICAL / SUPERSEDED — preserved as RCA and repair evidence; not current behaviour
**Owning repository:** `ContextualWisdomLab/.github`
**Canonical repair PR (historical):** `#1630`
**Superseded by:** `#1878`, merged `1b65dbc35e7183722ad77894e2d80b39993be90d`, which removed the
organization-wide `org-queue-sweep` source outright; later lineage adds
`85f4ef926feed08cf502a8e6bf26e495a0bb7bed` ("ci(actions): fold head coalescing into scheduler").
Both are ancestors of protected `main@c9052e607e5f3cc76e73207e7786b21500721b79`, whose scheduler tree
contains no such job.

> **Read the rest of this document as history.** The 15-minute admission, the hourly heartbeat that
> replaced it, and the rotation-counter cadence all describe a job that no longer exists. Nothing
> here is a current production contract, no new deletion implementation is required, and this
> document must not be cited as evidence about present queue behaviour. The RCA and the repair record
> are kept intact deliberately.

**Protected baseline:** `main@4ae90e18b03a3a455e13e501628010cabc5c37a8`

## Root cause

The central PR review/merge scheduler has two periodic entry points in addition to event-driven wakes. The repository-local queue scan runs every 30 minutes, while the expensive `org-queue-sweep` has been admitted every 15 minutes. Under the observed organization-wide hosted-runner saturation, the full organization walk can remain queued or run long enough that quarter-hourly admission adds more pending work before prior evidence drains. That is a control-plane pressure amplifier: required current-head evidence for leaf repositories queues behind recurring control-plane work that exists to unblock those same repositories.

The repair is deliberately bounded. Keep the 30-minute repository scan and all event-driven `pull_request_target`, `pull_request_review`, `workflow_run`, and `repository_dispatch` wakes. Change only the organization sweep heartbeat to hourly (`0 * * * *`). The wall-clock fallback used by the persisted sweep rotation counter must advance on the same hourly cadence (`epoch_seconds / 3600`) rather than the old 15-minute cadence (`epoch_seconds / 900`), otherwise a fallback run would skip four repository offsets for each real scheduled sweep.

## TDD and executable contract

`tests/test_actions_queue_saturation_scheduler_cadence.py` is the RED-first contract. It requires the live workflow to contain the hourly cron, rejects the quarter-hourly cron, preserves event-driven wakes, and binds both wall-clock fallback expressions to hourly rotation. The older assertions in `tests/test_required_workflow_queue_contract.py` must be updated with the production workflow rather than retained as a stale policy test.

The production change must also update `docs/org-required-workflow-rollout.md` so operator guidance states that the heartbeat can be up to one hour old. Historical doctoring that describes the old quarter-hour schedule remains historical evidence and must not be rewritten as though it never existed.

## Safety boundary

This repair does not mark queued checks successful, cancel the sole current-head evidence, weaken required workflows, relax approval requirements, or synthesize review state. A later 2026-09-04 ownership repair removed cross-repository Actions-run cancellation from this sweep; native per-PR concurrency and the local exact-head coalescer now own supersession. Cross-repository mutation credentials, unavailable-repository thresholds, scheduler concurrency groups, and merge guards remain unchanged.

No organization-owned identifier introduced by this repair uses an ambiguous single-word domain name. GitHub event fields and cron syntax are externally mandated contract terms and remain unchanged except for the cadence value.

## Verification

After the production commit lands on the canonical branch:

1. run the focused cadence and required-workflow queue contract tests;
2. verify the scheduler workflow contains exactly the intended 30-minute repository scan and hourly organization sweep;
3. confirm event-driven wakes remain present;
4. inspect fresh exact-head required checks and review evidence;
5. observe queue depth after the change rather than treating the configuration diff itself as proof that saturation has cleared.

Merge remains subject to ordinary protected-branch requirements and exact-current-head evidence.
