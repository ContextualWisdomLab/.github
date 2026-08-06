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

## Rollback and incident response

Roll back the allowlist and regression together only if a downstream call is
proven to evaluate normalized paths as shell source. Until that defect is fixed,
fail Strix closed and retain the offending path, workflow run, and commit SHA as
incident evidence. Do not bypass the required security check.

## References

Git Project. (2026). *Git index format*. https://git-scm.com/docs/index-format

Git Project. (2026). *git-ls-tree documentation*. https://git-scm.com/docs/git-ls-tree

Python Software Foundation. (2026). *pathlib—Object-oriented filesystem paths
(Python 3.14.6 documentation)*. https://docs.python.org/3.14/library/pathlib.html

Batchelder, N., & contributors. (2026). *coverage.py 7.15.2* [Computer
software]. Python Package Index. https://pypi.org/project/coverage/7.15.2/

pytest development team. (2026). *pytest 9.1.1* [Computer software]. Python
Package Index. https://pypi.org/project/pytest/9.1.1/
