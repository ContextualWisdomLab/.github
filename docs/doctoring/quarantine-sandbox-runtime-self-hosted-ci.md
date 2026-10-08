# Quarantine sandbox runtime: central self-hosted CI

## Status and ownership

This is a future routing definition, not working runner capacity or release evidence.
The operator-requested dedicated group `CWL QSR hostile workload` is
**NOT_PROVISIONED** under this handoff's current group-absence baseline, pending
ContextualWisdomLab/.github#1590. It must not be interpreted as a deployed group.
This writer did not query or change runner inventory, registration, labels or ACL.
The parent retains the inventory receipt and activation decision.

ContextualWisdomLab/.github#1590 owns dedicated disposable runner capability and
custody. ContextualWisdomLab/.github#2083 owns reusable positive-LSM publication
and operational acceptance. Both issue bodies were read on 2026-10-08; neither
is closed by this source-only extraction. Existing central control, CodeQL,
OpenCode, isolated and remediation groups are not fallback capacity.

Owned files are the reusable workflow, its static Python contract tests and this
record only. Shared governance files, Goal thresholds and runner policy are not
changed. Independent security review and parent review remain required; this
writer supplies no self-approval.

## Fixed interface and candidate binding

`.github/workflows/quarantine-sandbox-runtime-ci.yml` accepts **workflow_call
only**, with no inputs, declared secrets or outputs. In particular, there is no
`candidate_sha`, `lane`, runner selector or test-selector input. One aggregate
call contains four eligible product jobs plus explicit admission and terminal
acceptance jobs. Terminal acceptance requires all five dependencies to report
success; missing, skipped, failed or cancelled dependencies are nonpassing. The separate product caller must
pin a reviewed immutable central commit SHA; a mutable branch is not publication.
Do not pass `secrets: inherit` or an environment carrying credentials.

The GitHub context is the caller's context. A dedicated `admission` job runs before
any checkout or product command. It must fail for repositories other than
`ContextualWisdomLab/quarantine-sandbox-runtime`, fork pull requests and
unsupported events. The retained product jobs still require either push or a
native same-repository pull_request. Other repositories, fork PRs,
pull_request_target, workflow_dispatch and repository_dispatch do not qualify.
The original positive push/same-repository guard is retained and narrowed by the
repository/event gate. **Native fork PR product execution: NOT_RUN; admission:
FAILED**. No skipped product job is acceptance evidence.

The candidate is derived solely from
`github.event.pull_request.head.sha || github.sha`. Each job checks out that
candidate with the original SHA-pinned checkout action, `persist-credentials:
false`, then compares `git rev-parse HEAD` against the event-derived SHA before
installing tools or executing product code. The workflow grants only
`contents: read`, contains no publication/write commands, credential inheritance
or write permission, and uploads only the original coverage evidence artifacts.
Artifact upload is not a repository-write permission grant.

Reusable concurrency is workflow-scoped and namespaced `qsr-central-`, then
workflow/repository/PR number with run-ID fallback and cancellation enabled.
The caller must use a different group namespace to avoid self-cancellation.
There is no central helper-code checkout and no new `job.workflow_*` expression.

## Retained lanes and lost capability

All jobs require group `CWL QSR hostile workload` with labels `self-hosted`,
`linux`, `cwl-hostile-workload`; positive LSM additionally requires `selinux`.
There is no GitHub-hosted fallback or user-selected runner routing.

| Child job | Preserved mechanics |
| --- | --- |
| `verify` | Rust 1.97.1; locked metadata/test/clippy; repository policy; coverage-parser unit tests; fmt; rustdoc with warnings denied |
| `coverage` | Rust 1.97.1 + llvm-tools-preview; cargo-llvm-cov 0.8.6 locked install; workspace lib/tests JSON and strict production parser |
| `branch-coverage` | nightly-2026-07-01 + llvm-tools-preview; cargo-llvm-cov 0.8.6 locked install; branch JSON, missing-line report and `--require-branches` parser |
| `podman-e2e-positive-lsm` | Rust 1.97.1; exact Podman 5.8.4; nonempty runner name; rootless and SELinux boolean assertions; immutable pre-pull; real service isolation/cleanup witness; always-run zero container/network leak assertions |

The fixture remains
`docker.io/library/python@sha256:94457973ea8a27a799f0b8ea1fe3e3147fcbebaed63497a8af63b28195a08108`.
All action SHAs, product commands, environment values and coverage artifacts are
retained from the actual product source, with one independently reproduced
cleanup repair: enumerate networks first and fail on enumeration error before
checking names. The old pipeline's `|| true` incorrectly accepted query failure
as zero leaks. Container-query errors and visible container/network leaks remain
nonpassing. Synthetic shell controls verify these exits, not real isolation. Production statement/function/region/branch
coverage requirements remain exact **100%** where the parser exposes them; no
threshold, warning, isolation or cleanup requirement is relaxed.

`podman-e2e-negative-rootless-apparmor` is deliberately **DISABLED** and omitted.
The hosted Ubuntu 24.04 / Podman 4.9.3 producer's rootless unavailable-effective-LSM
rejection-and-cleanup witness is lost. It is not migrated to an unverified
self-hosted AppArmor profile and is not represented as passed by positive SELinux,
unit tests or skipped checks. Restoring a negative producer needs separately owned
capability and real unchanged-candidate evidence.

## Check-name migration is not branch protection compatibility

An aggregate reusable call changes published child check names. If the product
caller job ID is `ci`, the expected mapping to verify in a real Actions run is:

| Previous direct job | Expected nested check name |
| --- | --- |
| New admission rejection | `ci / admission` |
| New terminal evidence result | `ci / acceptance` |
| `verify` | `ci / verify` |
| `coverage` | `ci / coverage` |
| `branch-coverage` | `ci / branch-coverage` |
| `podman-e2e-positive-lsm` | `ci / podman-e2e-positive-lsm` |

A different caller ID/name changes this prefix. These are planning mappings,
not observed check-run names. Existing required-check names and branch protection
have not been queried or changed by this writer. Do not claim compatibility:
the parent must inspect actual published contexts and obtain the policy owner's
reviewed migration before treating these checks as replacements. The terminal
`ci / acceptance` check must also be enforced; requiring only filtered product
jobs is insufficient. No branch protection mutation was performed. Calling this
all-job interface three times would duplicate all four jobs, not select lanes.
A QSR #151-based caller does not automatically include QSR #150 static-analysis
lineage. Do not claim #150 coverage/adoption without an explicit rebase/merge and
separate verification. The peer's candidate_sha/lane oracle is not acceptance
of this no-input interface; a new independent verification must bind these final
source hashes, actual published central SHA and observed check-name mapping.
There is no published central SHA in this uncommitted, unpushed handoff.

## Admission and evidence still missing

Same-repository PR identity is **not security review authorization**. Exact HEAD,
read-only token and labels do not provide a safe prelease boundary. Product build
scripts, tests, parsers and dependency hooks execute hostile-capable code directly
on the selected host, even in the non-Podman jobs. There is no fabricated safe
prelease guard and no assertion that the product's container boundary protects
the CI host from its build process.

Before activation, #1590's owner must establish dedicated disposable custody,
absence of provider/production credentials, isolation from shared control planes,
and reviewed repository plus selected-workflow ACL restrictions bound to the
approved immutable central workflow. Do not register, relabel or expand existing
groups to make this definition run. Missing group/capability remains blocked or
queued, never a hosted fallback or operational success.

#2083 is broader than this source baseline: its production command timeout
witness
`production_gated_command_execution_kills_and_reports_a_command_that_exceeds_its_timeout`
and `x86_64-unknown-linux-musl` target are absent from the inspected source job.
This extraction does not invent either or claim complete #2083 acceptance. The
product owner must supply their reviewed mechanics through a subsequent exact
source change. Current-head positive service and command evidence, required
security/SBOM/provenance gates, independent review and protected integration
remain unresolved. No VM, compiler, cargo suite, container E2E or hosted execution
was run in this implementation task.

## Local source verification

Tests use PyYAML BaseLoader (preserving `on`) and a frozen in-test oracle from
the actual product CI bytes, not a runtime sibling-checkout dependency. Sequential
RED/GREEN receipts cover missing workflow, preserved mechanics, exact candidate,
read-only token, dedicated routing, admission, concurrency and this gap record.
Validation runs terminal `python3 -m pytest` only. Actionlint uses shellcheck and
pyflakes disabled as requested; custom-label configuration is scratch-only and
contains no expression suppressions. Neither static tests nor lint establishes
runner availability, operational isolation, qualifying approval or release readiness.

Primary platform references: GitHub Docs, **Secure use reference** (self-hosted
PR-code risk), **Reusing workflow configurations** (caller context/concurrency),
and **Reuse workflows** (immutable reusable references and permission boundaries).
Product source baseline SHA-256:
`1386ffe186ed9a903f5490289705bc7ee84a0bc3a9db62a1caf9b00238747813`.
The parent handoff carries frozen file hashes, full diff hash and raw local gate
outputs; none is promoted to successful operational evidence.
