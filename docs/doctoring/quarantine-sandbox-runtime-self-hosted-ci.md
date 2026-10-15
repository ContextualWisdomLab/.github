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

Owned QSR implementation consists of the reusable workflow, its Python contract
tests and this record. Source integration also declares the QSR custom labels in
`.github/actionlint.yaml` and binds the named group in the organization runner
contract. When merging the K-CSAP successor, keep its existing label and exact
workflow/job selector, and preserve the combined label set in its config test.
These source-only changes do not register runners or change ACLs or thresholds.
Independent source review is separate from a formal App review; this writer
supplies no self-approval.

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
any checkout or product command. Each of the four product jobs also executes a
trusted inline caller/event guard before its own checkout; this rejects a wrong
repository, fork, unsupported event, empty head, or non-lowercase/non-40-character
head. PR events require the raw `pull_request.head.sha`; push events require
`github.sha`. The admitted raw SHA must equal the effective checkout SHA. A missing
PR head cannot be accepted through the `github.sha` fallback, even if that fallback
is valid. The separate admission job alone is not treated as per-job protection.
It must fail for repositories other than
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
or write permission. Coverage uploads retain their JSON payloads and add a
run/head/content binding manifest under the SRC03 evidence-only slice.
Artifact upload is not a repository-write permission grant.

Reusable concurrency is workflow-scoped and namespaced `qsr-central-`, then
workflow/repository/PR number with run-ID fallback and cancellation enabled.
The caller must use a different group namespace to avoid self-cancellation.
There is no central helper-code checkout and no new `job.workflow_*` expression.

## Retained lanes and lost capability

All jobs require group `CWL QSR hostile workload` with labels `self-hosted`,
`linux`, `x64`, `cwl-hostile-workload`; positive LSM additionally requires `selinux`.
The organization runner policy contract admits this static group only with
`cwl-hostile-workload`; actionlint label declarations are source validation only.
There is no GitHub-hosted fallback or user-selected runner routing.

| Child job | Preserved mechanics |
| --- | --- |
| `verify` | Rust 1.97.1; locked metadata/test/clippy; repository policy; coverage-parser unit tests; both product-owned caller contract modules; fmt; rustdoc with warnings denied |
| `coverage` | Rust 1.97.1 + llvm-tools-preview; cargo-llvm-cov 0.8.6 locked install; workspace lib/tests JSON and strict production parser |
| `branch-coverage` | nightly-2026-07-01 + llvm-tools-preview; cargo-llvm-cov 0.8.6 locked install; branch JSON, missing-line report and `--require-branches` parser |
| `podman-e2e-positive-lsm` | Rust 1.97.1; exact Podman 5.8.4; nonempty runner name; rootless and SELinux boolean assertions; immutable pre-pull; real service isolation/cleanup witness; always-run zero container/network leak assertions |

The fixture remains
`docker.io/library/python@sha256:94457973ea8a27a799f0b8ea1fe3e3147fcbebaed63497a8af63b28195a08108`.
All action SHAs, compiler/tool pins, product acceptance commands and environment
values are retained. SRC03 changes only the two coverage evidence destinations,
adds binding manifests and names the artifacts by head/run/attempt. The earlier
independently reproduced cleanup repair remains: enumerate networks first and
fail on enumeration error before
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

## Caller contract enforcement

The `verify` job executes both product-owned caller modules after checking the
candidate HEAD, using `python3 -B -m unittest scripts/test_central_ci_caller.py
scripts/test_central_ci_caller_sensitivity.py`. The invocation is unconditional;
a missing module or either module's failure fails this job. There is no optional
skip, alternate path, or failure masking. The caller's reviewed full-SHA oracle
must be updated together with its workflow pin when adopting a successor.
Running this producer against a predecessor without these modules fails closed.
Their tests do not replace host prelease isolation or actual execution evidence.

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
The caller must retain its existing immutable pin until a reviewed successor is
published. A local integration or a new main revision does not update that pin.

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
Verification uses the QSR contract module plus the adjacent runner-policy and
K-CSAP integration contracts. Actionlint runs against the QSR workflow with its
normal external scanners and the committed custom-label config; a scoped pass is
not a repository-wide actionlint pass. Neither static tests nor lint establishes
runner availability, operational isolation, qualifying App approval or release readiness.

## Exact positive-LSM execution witness

`LSM-TEST-001` addresses the zero-test-success finding on central PR #2601:
`--exact` alone does not require a matching test. The trusted inline wrapper
executes the immutable named ignored test with libtest pretty output, one test
thread, no color and stdout capture enabled. It preserves a nonzero Cargo exit
and requires exactly one running-count line, exactly the named passing-test line,
and exactly one summary with one pass and zero failures, ignored or measured
tests. Empty, renamed, ignored, duplicate or inconsistent results fail closed.

The transcript stays in the executing wrapper rather than a reusable fixed file;
Python isolated mode prevents candidate-root module imports by this wrapper.
Synthetic Cargo-output controls test admission, not Podman or kernel isolation.
This check detects absent/renamed tests, not a malicious candidate that forges
libtest output or weakens the test body. Code review and disposable host custody
remain necessary. Fresh source/tool/process directories and actual positive-LSM
execution are separate, unfinished activation work. The SRC03 slice below
addresses only coverage artifact-path hygiene, not hostile-writer isolation.

## SRC03 evidence-path slice (2026-10-14)

The initial source-bound RED replayed the parsed baseline generation commands
with a reached synthetic Cargo producer returning zero and leaving a symlink to
foreign bytes. Both lanes reached the pre-upload boundary without rejecting it;
regular-file positive controls also passed. This is not an Actions upload claim.
A failed generation already suppresses the default-success upload, so stale
files after a nonzero generation are **not** described as an exploitable RED.

Both coverage lanes now exclusively create a mode-0700 immediate-child directory
under canonical `RUNNER_TEMP`, named with the admitted run ID, attempt, lane and
candidate HEAD. Existing directories or symlinks fail without deletion or
adoption. The trusted isolated inline producer verifies HEAD before/after Cargo,
retains nonzero exits, and requires a nonempty single-link regular output through
no-follow/nonblocking descriptor reads. It emits an exclusively created
`binding.json` containing run/attempt/lane/head, root device/inode, payload name,
byte count, SHA-256 and the zero producer exit. There is no candidate helper
import, new checkout, token permission or failure masking.

Immediately before the unchanged SHA-pinned upload action, isolated trusted code
checks root type/owner/mode and recorded inode, rejects duplicate/unknown binding
fields and Boolean-as-integer values, rehashes nonempty regular bytes and checks
HEAD again. Upload includes the JSON and manifest, with head/run/attempt in its
name. The strict product parser still follows upload, using the exact admitted
path, and branch coverage still requires nonzero branch instrumentation and
100% owned production coverage. Upload remains default-success only: failed
production or admission cannot publish through `always()`.

Synthetic source-bound controls cover legitimate output with spaces in the temp
path; successful symlink/empty/missing/directory/FIFO/hardlink output; nonzero
producer exit; prior root and root symlink; and post-production changes
to run/attempt/head/lane/size/hash/producer exit, duplicate/unknown fields, payload
and root nodes. Foreign sentinels are preserved. These are local wrapper controls,
not actual Cargo coverage generation or `actions/upload-artifact` execution.

SRC03 review repairs B01/B02/R03 retain literal, reviewed producer/guard script
SHA-256 contracts and the exact immutable upload `uses` value. Mechanics compare
actual step projections, complete env/step schemas and ordering; they do not
replace observed runtime steps with baseline objects. Persistent mutations cover
mutable/alternate-SHA uploads, substituted generators/guards and removed/bypassed
admission. The existing behavioral source controls remain required.

Both producers use portable `hashlib.sha256().update()` chunk loops, not
`file_digest`; the missing-API child test is a synthetic stdlib-capability seam,
not observed minimum-version or actual runner execution. The project Python
minimum is unchanged. Payloads have no arbitrary size cap: both producer and
reader hash chunks of at most 65536 bytes, count bytes against descriptor size,
and compare device/inode/type/owner/link count/size/mtime/ctime before and after.
Reads consume at most the initially observed size plus one detection byte,
refusing growth rather than following an unbounded append. Access time is not a
stability field because the read itself may update it.

`binding.json` is limited to **4096 UTF-8 bytes** before exclusive publication and
before decoding. Its closed schema contains four identity strings, a fixed
payload name, a 64-character SHA-256 and four integers; ordinary bindings are
well below this generous small bound. Pathological numeric identity lengths are
refused, not silently truncated. The reader bounds the read call itself to 4097
bytes, so a misleading size observation cannot permit an unsized allocation.
Tests execute actual bodies on a 2162688-byte regular payload, verify repeated
bounded reads and the independent digest/count, reject oversized serialization
before publication and oversized input even through the synthetic metadata seam,
and detect controlled grow/truncate during reads. These are bounded consistency
controls, not hostile-writer isolation or complete product-parser memory bounds.

**Incomplete:** Cargo/Rustup homes, installed tools, build target, and child
process settlement remain shared or unattested. Checkout, cwd, output, and
cleanup are bound to one job, admitted source HEAD, run id, and run attempt
under `qsr-job`. cwd is that checkout. output is its sibling, not the
evidence root. cleanup is only that job root. `podman-info.json` is placed
under output. `scripts.ci.qsr_source_artifacts` admits an output artifact only
when it is a nonempty single-link regular file inside that output and its
`.source.json` sidecar names the same source.
A stale sidecar or foreign output path, a symlink artifact, and an empty
artifact are refused separately as `SRC03-ART-STALE`, `SRC03-ART-SYMLINK`,
and `SRC03-ART-EMPTY`. The entrypoint records each fixture path against the
target source. Symlink fixtures are not followed. This binding is not hostile-writer isolation, signed provenance,
or runtime acceptance. No evidence-root deletion is added: failed/ambiguous
roots remain for operator-owned reconciliation after settlement. A directory name, mode, hash or
inode does not exclude a same-UID hostile process; product code can forge a
manifest and mutate bytes after admission or during upload. The manifest is
byte consistency, not a signed provenance attestation. Dedicated disposable
host custody, trusted tooling and race-safe artifact consumption remain required
before activation. The owner must independently review this slice and execute
Linux/runtime/Actions gates; the private scratch patch is not published source,
full-suite acceptance, App approval, runner provisioning or release evidence.

Primary platform references: GitHub Docs, **Secure use reference** (self-hosted
PR-code risk), **Reusing workflow configurations** (caller context/concurrency),
and **Reuse workflows** (immutable reusable references and permission boundaries).
Product source baseline SHA-256:
`1386ffe186ed9a903f5490289705bc7ee84a0bc3a9db62a1caf9b00238747813`.
The parent handoff carries frozen file hashes, full diff hash and raw local gate
outputs; none is promoted to successful operational evidence.
