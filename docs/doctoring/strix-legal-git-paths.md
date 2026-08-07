# Strix legal Git path compatibility

## Incident and buyer impact

The organization-required Strix quick gate rejected the exact changed-file list
for `ContextualWisdomLab/aFIPC#160` at head
`804ea97cd83144f94c5020a9d42f2573cc8cb442`. The pull request deletes generated
Packrat artifacts, including the tracked fixture path
`Ugly, but legal, path for a project (long)`. The central gate classified that
path as unsafe solely because its comma and parentheses were absent from the
bounded ASCII allowlist. Security analysis therefore stopped before examining
the pull request, leaving a valid supply-chain cleanup without exact-head Strix
evidence.

## Decision

The normalizer now admits comma and ASCII parentheses. No other punctuation is
broadened. Existing fail-closed controls remain authoritative:

- empty, dot, absolute, leading/trailing-whitespace, NUL, CR, LF, and
  backslash forms are rejected;
- raw `..` components are rejected before `posixpath.normpath()` can collapse
  an embedded traversal such as `safe/../target.txt`;
- shell metacharacters such as semicolon, dollar sign, backtick, pipe, and
  ampersand remain rejected;
- only the existing Unicode letter, combining-mark, and number categories are
  accepted outside ASCII;
- `Path.resolve(strict=False)` followed by `relative_to()` proves containment
  beneath the trusted repository root; and
- downstream Git and filesystem operations receive normalized paths as quoted
  arguments, never as executable shell source.

This is a compatibility correction, not a general relaxation to every pathname
byte Git can represent. The privileged scanner intentionally retains a smaller,
audited path policy.

## Test-first evidence

`tests/test_strix_changed_path_policy.py` extracts and executes the exact Python
normalizer embedded in `scripts/ci/strix_quick_gate.sh`. The materializer first
requires the historical Packrat fixture regression to fail on protected main,
then applies the narrow allowlist change and requires the same test to pass.
A test-only exact-head commit first demonstrated that `safe/../target.txt`
passed after normalization; the production repair now rejects its raw `..`
component before normalization. Permanent tests preserve established punctuation
and reject traversal, absolute paths, controls, whitespace ambiguity, backslashes,
and representative shell punctuation. The dedicated workflow runs the complete
repository test suite through coverage.py and pytest whenever code or either
authoritative contract document changes.

The complete shell regression is also part of the permanent quality job.
`scripts/ci/test_strix_quick_gate.sh` exercises the executable shell boundary,
and the workflow's path filter includes that script so a change cannot bypass
the suite merely because pytest does not collect shell files.

## Workflow dependency integrity

The exact-head policy workflow downloads its Python test runner from PyPI, so
version pins alone are insufficient: a compromised index response or replaced
artifact could otherwise change executable CI code without a repository diff.
The workflow therefore uses pip hash-checking mode (`--require-hashes`) together
with `--only-binary=:all:` and the exact SHA-256 digest of every wheel selected
on the fixed `ubuntu-24.04` x86-64 / CPython 3.14 runner:

- coverage 7.15.2: `b9a6367e4aff723e8ee8190836836124284e8fcd4265e307c844010cfa074f3f`;
- iniconfig 2.1.0: `9deba5723312380e77435581c6bf4935c94cbfab9b1ed33ef8d238ea168eb760`;
- packaging 26.2: `5fc45236b9446107ff2415ce77c807cee2862cb6fac22b8a73826d0693b0980e`;
- pluggy 1.6.0: `e920276dd6813095e9377c0bc5566d94c932c33b27a3e3945d8389c374dd4746`;
- Pygments 2.20.0: `81a9e26dd42fd28a23a2d169d86d7ac03b46e2f8b59ed4698fb4785f946d0176`;
- pytest 9.1.1: `37a86b45efb9a47a61a36449063e8e18d0cab3161329fc099eb21783169c4f0c`.

`tests/test_strix_workflow_dependency_hashes.py` was committed before the
workflow implementation and fails against the preceding exact head because
hash-checking mode and its trigger path are absent. It is now part of the
workflow's own path filter and verifies every requirement/digest pair. Any
package or runner-platform change must update the package version, PyPI wheel
digest, regression contract, and this record together. A digest mismatch must
fail closed; do not disable hash checking to restore availability.

## Trusted workflow-source boundary

A review suggestion proposed `workflow_dispatch` so operators could rerun this
quality job manually. That isolated suggestion conflicts with the stronger
central automation boundary: GitHub's manual workflow UI and API allow the
caller to select a branch or tag, and the selected revision supplies the
workflow definition before any in-workflow checkout or source validation can
run. A credentialed central workflow must therefore not expose branch-selected
manual execution unless a separate protected-default-branch dispatcher first
validates immutable target metadata.

The conflict was captured rather than silently ignored. Exact-head run
`31156812291`, job `92798043647`, executed the complete central suite after
`workflow_dispatch` was added and failed the organization contract
`test_no_central_workflow_exposes_branch_selected_manual_dispatch` with
`1 failed, 969 passed`. The workflow now remains pull-request-triggered only,
and `tests/test_strix_workflow_dependency_hashes.py` permanently rejects
reintroduction of branch-selected manual source. The valid parts of the review
remain implemented: the shell regression is a trigger path and is executed by
the permanent exact-head job.

A future operator/API rerun must be a separately designed default-branch-only
entrypoint that treats target repository, pull-request number, and exact head
SHA as untrusted bounded data. It must never execute a caller-selected workflow
revision or receive broader credentials merely to improve convenience.

## Quality-gate runtime budget

Exact-head Strix Changed Path Quality CI run `31222595171` for
`ContextualWisdomLab/.github#790` checked out
`c9f11e803b2d797604276b64a51c4ff47d9e3757`, installed the hash-locked test
runner, and completed the full central Python suite with `1,017 passed` and
`16 subtests passed` in about 55 seconds. It then entered the complete shell
regression harness, which intentionally exercises multiple bounded timeout and
fail-closed paths. GitHub cancelled the job at the configured ten-minute job
budget before that harness could finish; no failing assertion preceded the
cancellation.

That cancellation is not passing security evidence and is not a reason to remove
or shorten the shell regressions. Test-first commit
`1912d39d7d9b395e66c6bdb7cfcd37f31850f37f` adds a permanent contract requiring
the quality job to reserve at least 20 minutes while preserving the harness's
30-second process-timeout and 60-second fake-sleep boundaries. Production commit
`e0ea9cea372286eefcfb914b2113554d93654ffe` raises only the job-level
`timeout-minutes` from 10 to 20. It does not change test selection, assertions,
coverage requirements, dependency integrity, security classification, or scanner
behavior.

GitHub documents `jobs.<job_id>.timeout-minutes` as the maximum time before a job
is automatically cancelled. A larger explicit budget therefore preserves a
bounded failure mode while allowing the already-bounded regression harness to
complete. Future changes must keep the workflow budget above the measured
worst-case harness envelope; if the harness gains additional bounded waits, the
budget contract and this record must be reviewed together rather than deleting
slow security tests.

## Rollback and incident response

Roll back the allowlist and regression together only if a downstream call is
proven to evaluate normalized paths as shell source. Until that defect is fixed,
fail Strix closed and retain the offending path, workflow run, and commit SHA as
incident evidence. Do not bypass the required security check.

If an exact dependency wheel becomes unavailable, first verify the release and
artifact digest against PyPI's file record and provenance. A rollback may select
the last known-good fully versioned wheel only when its exact hash is recorded in
the workflow, regression contract, and this document. Never replace
`--require-hashes` with an unhashed install.

Do not restore `workflow_dispatch` to this executable central workflow as an
availability workaround. Use a new pull-request event, a protected-main change,
or a separately reviewed immutable-target dispatcher.

Do not roll the Strix quality job back to a budget that is shorter than its
complete bounded regression harness. If runtime becomes unacceptable, optimize
or decompose the harness with equivalent coverage first and retain exact-head,
fail-closed evidence throughout the migration.

## References

Batchelder, N., & contributors. (2026). *coverage.py 7.15.2* [Computer
software]. Python Package Index. https://pypi.org/project/coverage/7.15.2/

GitHub. (2026). *Workflow syntax for GitHub Actions*. GitHub Docs.
https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax

GitHub. (2026). *Manually running a workflow*. GitHub Docs.
https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow

GitHub. (2026). *Events that trigger workflows*. GitHub Docs.
https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows

Git Project. (2026). *Git index format*. https://git-scm.com/docs/index-format

Git Project. (2026). *git-ls-tree documentation*. https://git-scm.com/docs/git-ls-tree

Python Packaging Authority. (2026). *Secure installs*. pip documentation.
https://pip.pypa.io/en/stable/topics/secure-installs/

Python Software Foundation. (2026). *pathlib—Object-oriented filesystem paths
(Python 3.14.6 documentation)*. https://docs.python.org/3.14/library/pathlib.html

pytest development team. (2025). *iniconfig 2.1.0* [Computer software]. Python
Package Index. https://pypi.org/project/iniconfig/2.1.0/

pytest development team. (2025). *pluggy 1.6.0* [Computer software]. Python
Package Index. https://pypi.org/project/pluggy/1.6.0/

pytest development team. (2026). *pytest 9.1.1* [Computer software]. Python
Package Index. https://pypi.org/project/pytest/9.1.1/

Python Packaging Authority. (2026). *packaging 26.2* [Computer software].
Python Package Index. https://pypi.org/project/packaging/26.2/

Pygments contributors. (2026). *Pygments 2.20.0* [Computer software]. Python
Package Index. https://pypi.org/project/Pygments/2.20.0/
