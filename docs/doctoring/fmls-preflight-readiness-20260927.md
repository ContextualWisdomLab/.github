# fast-mlsirm review-gate continuation: readiness repair

## Original intent and boundaries

Independently review ContextualWisdomLab/fast-mlsirm#2114 and
ContextualWisdomLab/fast-mlsirm#2120, then report shared CI failures to the
main or owning coordinator. Those PRs were merged on 2026-09-24. The previous
session stopped after the five-item report and correction of Cargo ownership.
This continuation preserves the numerical formulas, source transcript,
other agents' dirty worktrees, and protected review/security gates. It makes
no merge, tag, release, provider-availability, or hosted-acceptance claim.

## Current scope

DOI URL tests are now in ContextualWisdomLab/fast-mlsirm#2171 at
`cffb90fb742d0ebcb9c5aa49c8323ce349138eab`; six focused tests pass on that head
and after an isolated conflict-free merge with main `6dd48140`.

Existing central repairs were independently checked and received scoped
COMMENT reviews:

| Repair | Exact reviewed head | Local evidence |
| --- | --- | --- |
| #2360, committed Rust roots via `cargo vendor --sync --locked` | `fc9c8d2c8537e9a0582299d5b26eef31d6309710` | 26 passed; three real Cargo integrations excluded |
| #2385, proven target GHAS-read credential selection | `372f5b8bb1ae1bb32ab29e9afbe363d81aed81e3` | 59 focused tests passed |
| #2387, Noema retry dispatch credential separation | `33b9028318ddd0cf6c34d1816b09b94e95346c10` | 85 focused tests passed |

Those local results do not prove hosted credentials, provider capacity,
whole-PR approval, or deployment. The Noema repair addresses the observed
eligible HTTP 504 followed by integration HTTP 403 in run `36237188317`.
The Strix binder successor remains separately owned by #2291. The original
CodeQL-status permission and live governance requirements must be evaluated
from terminal producer evidence, not inferred from the GHAS-read test.

## New root cause and primary evidence

[Strix run 36237188327](https://github.com/ContextualWisdomLab/fast-mlsirm/actions/runs/36237188327),
job `108408520367`, artifact `10919666896` (`strix-reports`): discovery ends
at 19:06:31Z on 2026-09-26. Two OpenRouter probes return 429; gemma-3 probes
on both NVIDIA accounts return 404. Later probes complete (the next sequential
invocation demonstrates completion). `nvidia_nim` llama-3.2-90b begins at
19:06:49.173Z without any later outcome before hosted cancellation at
01:00:56.653Z on 2026-09-27. This is about 5h54m before readiness, gateway
preflight, or scanning. The preflight JSON is empty; sanitized stderr retains
the route invocation. ZIP SHA-256:
`7bfd559ac1abda65c150fc3d5ec99562d8c83fca1a8d9dc7b444f7de6a4304e7`.

The executed shared base is `e6334e229581a918e2f22de18733b76fa65d7e71`,
vendoring contextual-orchestrator `767e67fbc6b881a452761f32abb69b9971b9b03b`.
That runtime intentionally removed the 90-second inference deadline.
The sequential readiness walk consequently prevents later eligible routes
from being checked while a provider remains pending. Historical ADR-0029
wall-time bounds no longer describe that pin.

An event-controlled check against the exact base launcher confirmed that a
pending first call prevents all eight later readiness calls. An initial
concurrent implementation with only eight outstanding calls reproduced the
same obstruction with eight pending candidates, so the final scheduling uses
the existing sixteen-base-probe budget to bound outstanding calls as well.
It processes available completions before scheduling more work, preserves
catalog priority among admitted routes, and shares the four escalation
reservations across all probes and fallback. Pending calls continue without
admission or a synthetic failure verdict.

## Verification and remaining acceptance

The original runtime preflight suite and eight new concurrency checks pass:
143 tests with warnings as errors, both locally and with `GITHUB_ACTIONS=true`.
The event tests hold one or eight calls pending and require eight subsequent
ready routes to be admitted before releasing the pending calls. Other checks
cover all-429 failure, escalation bounds, deferred-route admission, fallback
ordering, fault propagation, and production wiring. Ruff and diff whitespace
checks pass. No live provider credential or model API was used in tests.

After this repair lands through normal protection, a fresh exact-head review
must show completed readiness and a valid reviewer receipt. Pools without
enough responding routes can still wait; hosting loss and durable resumption
remain distinct concerns. The snapshot's pending rows are startup evidence,
not final outcomes of those model calls. More simultaneous calls may expose
provider rate limits sooner, within unchanged total request budgets.

Organization-wide evidence found 51 assigned running jobs (30 Strix, 19 Noema,
two compatibility), while the #2171 OpenCode coverage and CodeQL producer jobs
were unassigned. This establishes occupancy, not the exact concurrency ceiling.
The Actions budget does not halt usage. Five oldest sampled review runs still
matched open current-head PRs; no stale cancellation was justified.

Owner report: [fast-mlsirm #2171 comment](https://github.com/ContextualWisdomLab/fast-mlsirm/pull/2171#issuecomment-5853298639).
Repair tracking: #2408, Project #1 In Progress. Hosted current-head acceptance
and qualifying independent review remain required.
