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

## 2026-09-27 security prerequisite integration

Noema #2387's hosted pip-audit job `108414598334` is a real shared-lock
failure: `requirements-strix-ci-hashes.txt` still selects AnyIO 4.14.0.
The audit lists CVE-2026-63374, CVE-2026-64847 and CVE-2026-63349, each with
4.14.2 as the patched version. This is separate from the startup scheduling
failure and the retry-dispatch credential defect.

The canonical dependency repair is #2278 at
`8a5251bf409fe84b3dd0cba1e48992f5b8d9eda5`. Its complete three-dot delta
against protected main is exactly the six-line AnyIO pin/hash change. The
current-head requested-changes review cites failed coverage and contains no
source-backed lock finding; there are no inline review comments. That review
is retained, and no approval or main merge is inferred from the dependency
verification.

An ordinary two-parent integration carries the canonical owner's exact commit
into this isolated repair branch. The integration changes only that lockfile;
it does not modify the owner's branch or copy unrelated foundation repairs.
The release wheel and sdist were downloaded from PyPI's official distribution
host and their actual SHA-256 bytes matched both committed hashes:

- wheel: `9f505dda5ac9f0c8309b5e8bd445a8c2bf7246f3ce950121e45ea15bc41d1494`
- sdist: `cfa139f3ed1a23ee8f88a145ddb5ac7605b8bbfd8592baacd7ce3d8bb4313c7f`

A hash-pinned pip-audit 2.10.1 installed in an isolated project venv audited
all 106 distributions listed in the original and repaired Strix lock, with
`--strict --disable-pip --no-deps --format json`. The original returns exit 1
with exactly those three AnyIO findings; the repaired lock returns exit 0
with zero findings. Both JSON results contain 106 dependencies and zero
skipped entries. Target dependencies were not installed or executed. HTTP
cache entries that could not be decoded were ignored by the tool; the audit
completed. This establishes the changed lock's advisory result, not the
security of every repository input or a live Strix run.

Primary advisory basis: [AnyIO process-pool stderr advisory](https://github.com/agronholm/anyio/security/advisories/GHSA-5p39-cfhj-2xmp)
and [supplementary-group advisory](https://github.com/agronholm/anyio/security/advisories/GHSA-3w57-8xmc-8v26).
The existing gate and its severity/ignore policy remain intact.

## Current governance audit and correction of the historical diagnosis

Live ruleset `18156473` still requires seven `.github@main` workflows,
including `codeql-pr.yml`. That CodeQL entry is intentional: the protected
rollout document's 2026-09-04 correction restored a dispatch-safe entrypoint
that does not directly invoke `github/codeql-action`. The earlier transcript's
claim that its presence disagreed with the removal policy is superseded by
that correction. The July inventory warning still described removal/native
setup as the current posture; this continuation repairs that stale wording
without changing a required gate.

The live organization payload also reveals a separate approval-policy
mismatch. Its approving-review count is one and last-push approval is false;
protected main's audit contract and July 23 rollout evidence require two and
true. Running the existing auditor on the actual payload returns exactly those
two errors. All seven workflow identities, required source ref, exclusions,
stale-review dismissal, review-thread resolution, and branch protection rules
pass that audit. The stacked ruleset `21732164` separately passes its audit.
Code-owner review remains false as the maintainer requires.

An unapplied candidate changing only those two approval fields passes the
existing auditor. The current payload's SHA-256 is
`d6e6efd8c67027ae4a3625753c0e90198f8f92c67c691a0857231bd81d8ce412`.
The audit-log endpoint returned HTTP 404, so the reason or authority for the
live approval settings cannot be established from that endpoint. The user has
been asked which approval policy is intended before changing organization-wide
merge conditions or the repository contract. No live ruleset has been changed.
This mismatch does not explain an unassigned CI runner; job
`108568126406` and the original OpenCode coverage job `108521250487` are
separately confirmed queued with runner_id zero and no executed steps.
