# OpenCode infrastructure failures and review state

Status: Proposed; protected delivery and downstream exact-head review are unverified.

## Causal evidence

CO #1223 at 90911687cb1ee49325ddd1f2bdfd29284a526028 was returned to Draft
because older OpenCode reviews remained CHANGES_REQUESTED. Their bodies explicitly
reported no source-backed product finding. Central run 36081670283, coverage job
107989271158, failed its trusted Docker image build before any CO test executed:
requirements-noema-document-ci-hashes.txt was missing from the build context.
That independent source defect is owned by ContextualWisdomLab/.github#2286 and #2385.

The fallback publisher unconditionally used REQUEST_CHANGES to satisfy the formal
receipt gate. This promoted missing infrastructure evidence into a product verdict.
The correction publishes COMMENT instead and retains COVERAGE_BLOCKED separately.
COMMENTED still fails the formal receipt gate, never grants approval, and never
satisfies merge acceptance. Real source-backed model findings retain REQUEST_CHANGES.
Old reviews are not dismissed. After infrastructure delivery, a fresh model review
and required checks must settle against the exact current target head and base.

## Verification

The new event regression fails on unmodified main (1 failed, exit 1). Focused
publisher, coverage identity, receipt, pinned-workflow and toolchain contracts pass:
88 passed, 1 skipped, exit 0. actionlint and git diff --check pass. No hosted Docker
build or protected merge is claimed. The deterministic fallback source body is
unchanged; only its GitHub event is diagnostic rather than a fabricated verdict.
