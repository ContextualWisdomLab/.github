# PR head replay guard: existing-file replacement evidence

## Incident

`ContextualWisdomLab/ContextualWisdomLab.github.io#144` exposed a false-positive boundary in the organization-owned post-merge stale-agent replay guard. On exact head `dbc0757718e92d56b4d0f4a5bc56be686a18e5d3`, the guard correctly observed that `tests/test_component_gallery_security.py` lost declared test cases after merge anchor `eb677d0b46bd35cd548b75b1506cedfc80c0b9b2`, but it treated `added_test_files == 0` as proof that no replacement coverage existed.

The same post-merge range strengthened the already-existing `tests/test_component_gallery_resilience.py` from one declared Python test to three. In particular, the new executable keyboard-navigation harness covers wrapped ArrowLeft/ArrowRight navigation plus Home/End activation and state transitions. Because the replacement lived in an existing test module rather than a newly created file, the old guard rejected the head before coverage evaluation even though the test inventory grew.

## Root cause

`test_file_changes()` recognized two kinds of evidence only:

1. regressions from deleted test files or reduced declared test-case counts; and
2. replacement from a newly added test file.

It did not represent a positive declared-test-case delta in an existing test file. The result was a filename-level replacement heuristic applied to a test-case-level regression signal.

The same boundary originally evaluated declared-case loss only for `M` numstat
records. A Git-detected `R` record carries both the old and new path and is
excluded from that modified-file pass, so a renamed test module could lose a
declared case without producing regression evidence.

## Bounded repair

The existing `test_file_changes()` return contract remains unchanged so callers and focused tests do not need an unrelated API migration. A separate read-only helper counts only positive declared-test-case deltas for supported test files that exist at both revisions. `ReplayEvidence` records that count and classifies a test regression as suspicious only when all three conditions hold:

- at least one test path regressed;
- no new test file exists; and
- no declared test case was added to an existing test file.

Deleted files, malformed or unsupported test sources, unevaluable revisions, exact pre-merge tree replay, targeted unmerge of base work, and the conservative bulk-deletion signature remain fail-closed. The change does not infer semantic equivalence between old and new tests; it preserves the guard's existing coarse replacement policy while making file-level and case-level replacement evidence symmetric.

For a Git-detected test-to-test rename, the guard now evaluates the old path at
the start revision and the new path at the end revision. A smaller or
unevaluable declared-case inventory records the new path as regressed; the
rename does not manufacture added-file replacement credit.

Every replay-evidence `git diff` forces rename detection, so a repository-local
`diff.renames=false` setting cannot degrade the comparison into independent
delete/add records and manufacture replacement credit. A rename from a test
path to a non-test path records the old test path as regressed because the file
has left ordinary test discovery; the reverse direction counts as one added
test file, and a rename wholly outside test paths remains irrelevant.

## Verification contract

The permanent regression fixture models one existing test module losing a declared case while another existing module gains one. The old implementation cannot satisfy the fixture because it has no existing-file replacement signal. The repaired implementation reports the regressed path, zero added files, one added existing-file case, and does not classify that bounded refactor as stale replay.

A second fixture proves malformed numstat rows, binary entries, non-test files, unchanged case counts, missing before/after evidence, and case-count reductions cannot manufacture replacement credit.

A real temporary Git repository also renames a Python test module and changes
one declared `test_*` function into a non-test helper while local configuration
disables rename detection. The predecessor degrades the change into a deletion
plus a credited added test file; the repaired guard still reports the renamed
path, zero added test files, and a blocking test-regression signal. A second
fixture moves an unchanged test module outside test discovery and proves that
boundary crossing is reported as test loss.

Consumer acceptance requires rerunning the guard against the unchanged `ContextualWisdomLab.github.io#144` head and then regenerating its exact-head `coverage-evidence` and semantic review through protected organization workflows. A passing source test on this branch is not consumer or merge authority.

## Rollback

Rollback is a normal protected revert of the added existing-file case signal. Do not replace it with a broad line-addition threshold or a generic test-directory exception: those alternatives would turn unrelated test churn into synthetic replacement evidence. If a future guard needs semantic replacement matching, introduce it as a separately reviewed policy with explicit language/framework support and adversarial regressions.
