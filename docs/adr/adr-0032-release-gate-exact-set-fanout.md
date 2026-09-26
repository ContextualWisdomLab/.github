---
title: "ADR-0032: Bind release dependency verdicts to the complete artifact set"
status: "Proposed"
date: "2026-09-26"
authors: "CWL release gate maintainers"
tags: ["architecture", "decision", "release", "supply-chain"]
supersedes: ""
superseded_by: ""
---

# ADR-0032: Bind release dependency verdicts to the complete artifact set

## Status

**Proposed**. No release HOLD may be removed on the strength of this record. The
implementation and exact-head hosted evidence are still required by #2342.

## Context

The reusable gate in #2347 scans all resolved dependencies sequentially in one
360-minute job and seals one wheel and one sdist. ContextualWisdomLab/fast-mlsirm#2135 builds twelve
wheels and one sdist. Its admission job currently exits with an unconditional HOLD
because the existing handoff does not authenticate a same-run full licence and
Strix verdict or the complete release artifact set. A successful two-file seal
cannot establish a verdict for the other eleven wheels.

GitHub Actions reusable-workflow outputs from a matrix contain the value from
the last successful completing call that set a value. That output cannot
represent a complete verdict set. A matrix job's aggregate result can prove
that every invocation succeeded, but still does not identify which artifacts
each invocation examined. An uploaded JSON field claiming `PASS` is likewise
not a trusted job conclusion.

## Decision

- **DEC-001**: The protected release workflow uses its existing
  `reproducibility-record` job to produce one immutable, same-run manifest of
  all thirteen publishable fast-mlsirm distributions. Each row carries target,
  filename, file SHA-256, upload artifact ID, name, and archive digest. The
  trusted job enforces the expected twelve-wheel-plus-one-sdist set before it
  passes the manifest's ID and digest to the central gate.
- **DEC-002**: The central reusable gate takes that manifest by immutable
  artifact ID and digest, checks its run ID and attempt against the current
  invocation, downloads every referenced artifact by ID, and recomputes every
  file digest. It derives the dependency set and synthetic fixtures from the
  exact release source and collected build evidence before any Strix credential
  exists. Missing, duplicate, extra, expired, wrong-run, wrong-attempt, or
  wrong-digest evidence fails the gate.
- **DEC-003**: Strix runs in a dynamic matrix with exactly one dependency
  fixture per job. Each job uses the pinned trusted helper, the same source SHA,
  and an isolated fixture; it uploads a uniquely named immutable binding that
  includes dependency identity, fixture digest, source SHA, run ID, and attempt.
  The matrix fan-out has a reviewable concurrency bound and refuses a fixture
  set above GitHub Actions' 256-job matrix limit. Elapsed model time is not
  converted into a passing or failing security verdict.
- **DEC-004**: A downstream collector runs only when the licence stage and
  every matrix job succeeded. It compares the exact expected dependency keys
  with the binding-artifact keys, checks every binding and digest, and produces
  one full-set verdict artifact with its own ID and digest. It does not aggregate
  matrix job outputs and it cannot turn a failed or skipped scan into success.
- **DEC-005**: fast-mlsirm admission depends on the pinned central reusable
  gate's job result in the same workflow run. It verifies the returned verdict
  artifact by ID and digest, source SHA, run ID and attempt, and equality of all
  thirteen distribution rows to its locally verified manifest. It also
  requires a trusted, target-specific closure inventory for runtime, build,
  dev, optional, native, and bundled scopes. An `UNKNOWN` scope or a
  declaration identity without resolved dependency evidence refuses
  admission. Only then may it write `admitted-manifest.tsv`; the existing tag
  and publish jobs remain downstream of admission.
- **DEC-006**: The unconditional admission HOLD remains until hosted RED and
  GREEN runs on exact current heads prove this entire path, including a real
  Strix binding. Unit fixtures alone do not authorize its removal.

## Consequences

### Positive

- **POS-001**: The release verdict covers the bytes of every distribution the
  publish job can consume, including each wheel target.
- **POS-002**: An incomplete matrix, forged `PASS` document, or artifact from
  another run cannot satisfy the collector and admission contracts.
- **POS-003**: Each Strix scan has its own job lifetime, while the matrix's
  concurrency bound limits organization runner occupancy.

### Negative

- **NEG-001**: Fan-out and exact-set collection add jobs, artifacts, and
  validation code to a security-sensitive workflow.
- **NEG-002**: The full closure may occupy the Actions queue for many hours;
  queued jobs are pending evidence, not a passing verdict.
- **NEG-003**: The existing six-member, seventeen-output wheel/sdist
  attestation contract does not itself cover thirteen distributions. The
  full-set verdict must be verified separately until a reviewed generalized
  attestation contract replaces it.
- **NEG-004**: Source declaration hashes and one Ubuntu dependency capture do
  not establish the native and bundled closure of Linux, macOS, and Windows
  wheel build environments. Per-target collection and verification add work
  before the current scope HOLD can be removed.

## Alternatives Considered

### One sequential Strix job

- **ALT-001**: Keep the current single job and increase its timeout.
- **ALT-002**: Rejected because the job is already at GitHub's 360-minute
  ceiling, while one dependency's model path may take more than two hours.

### One reusable gate invocation per wheel

- **ALT-003**: Call the existing two-file gate twelve times, pairing each wheel
  with the same sdist.
- **ALT-004**: Rejected as the final design because it repeats the entire
  dependency scan twelve times. A caller can use the matrix job result and
  exact same-run artifact set without relying on its last-wins outputs, so
  this remains a possible intermediate wiring step while the release HOLD
  stays in force.

### Trust a seal or report by its filename

- **ALT-005**: Download a named artifact and accept its declared `PASS` field.
- **ALT-006**: Rejected because a name and a payload do not prove that the
  pinned gate succeeded in this run on these thirteen bytes.

## Implementation Notes

- **IMP-001**: First add RED cases for missing, duplicate, extra, stale-run,
  stale-attempt, wrong-source, altered archive, altered distribution, and
  omitted matrix binding. Include a scope record that remains `UNKNOWN` or
  substitutes declarations for a resolved platform inventory. Each must
  refuse before admission or publication.
- **IMP-002**: Keep source validation, pre-credential licence refusal, and
  immutable build-artifact intake from #2347. Preserve diagnostic artifacts on
  failures without an `always()` path that could allow downstream release jobs.
- **IMP-003**: The hosted GREEN case must exercise real capture, Strix,
  collection, sealing, and fast-mlsirm admission on an exact head. Record run
  and job IDs, all thirteen file digests, and the pinned central workflow SHA.
- **IMP-004**: Keep #2135 draft and release HOLD until #2342 acceptance and
  both repositories' exact-head required checks are terminal green. Merge,
  tag, and PyPI publication are separate later decisions.
- **IMP-005**: Preserve the existing unconditional refusal in
  `verify_scope_identities` as well as the workflow's final admission HOLD
  until the collector verifies all six scopes for every wheel target and the
  sdist. Removing only the workflow HOLD cannot make admission succeed.

## References

- **REF-001**: ContextualWisdomLab/.github#2342 and #2347; ContextualWisdomLab/fast-mlsirm#2135.
- **REF-002**: [GitHub reusable workflow matrix output behavior](https://docs.github.com/en/actions/how-tos/reuse-automations/reuse-workflows#using-a-matrix-strategy-with-a-reusable-workflow).
- **REF-003**: [GitHub Actions matrix output rules](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#jobsjob_idoutputs) and [immutable upload artifact IDs and digests](https://github.com/actions/upload-artifact/blob/main/README.md#outputs).
