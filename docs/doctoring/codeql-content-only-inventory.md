# CodeQL eligibility for document and evaluation-only repositories

## Observed failure

`ContextualWisdomLab/korean-writing-skills#4` at
`5a9a1cb85d748354a526813baed806911b827412` was not merely awaiting a scan.
Its required CodeQL run `36323616223` dispatched an `actions` shard to central
run `36343072762`. Job `108768482301` completed with CodeQL exit 32: no
supported source code was found. SARIF preservation and the security gate did
not run; refusing to publish a successful scan without that evidence was correct.

Two eligibility rules composed incorrectly. `Build language matrix` falls back
to `actions` when it finds no supported source. The changed-path classifier
considers evaluation JSON and `.gitignore` non-document changes, so a repository
containing only documents and evaluation receipts reaches that fictional shard.
GitHub documents unsupported or non-analyzable source as causes of this error
(GitHub, n.d.). This is not a reported source vulnerability and not evidence of
a successful security scan.

## Decision and boundary

Keep the existing named matrix job and its step-level guards. Before dispatch,
allow a narrow **CodeQL not applicable** result only when all of the following
hold: the PR-file API returned its complete expected count; the checked-out
`HEAD` equals the canonical event head; and the complete NUL-framed Git commit
tree contains non-executable regular blobs from the closed content allowlist.

The allowlist is Markdown/reStructuredText, exact root license/notice names,
root `.gitignore`, and JSON below `evaluations/`. It does not globally exempt
JSON, package manifests, source code, Actions YAML, unknown file types, links,
submodules, executable modes, malformed inventory, or missing evidence. The
inventory read is capped at 4 MiB; overflow retains the previous scanning path.
The two Git metadata reads each have a 30-second local-operation bound, not a
model-inference deadline. Temporary inventory storage is closed automatically.

The pure `content_only` policy is separate from the exact-head Git reader and
from the existing workflow dispatcher. The reader uses isolated standard-library
Python (`-I -S`), never runs repository scripts, and reads the commit tree rather
than a possibly sparse working directory. Unknown or failed reads retain
`code=true`. The existing document-only changed-path behavior is unchanged.

This is an applicability decision, not a security approval. Semgrep, Security
Scan, review requirements, and the CodeQL SARIF/GHAS/receipt rules for applicable
source remain unchanged. No synthetic status, dummy source, empty matrix,
trigger filter, or job-level required-context skip is introduced.

## Verification and limits

The baseline workflow blob was verified as
`8880d636638e927c574bdcc07ac3a71fe6422ff6` from protected main
`60cc284c2852ed318361bdb6cb0273b7e45fd3ef`.

The initial production-shell regression was RED: **1 failed, 29 passed**.
After the repair and malformed-inventory cases, the focused suite was GREEN:
**43 passed**, including warnings-as-errors. Tests execute the actual scope
shell against real isolated Git repositories; only the PR-files API is stubbed.
They cover source/unknown files, executable modes, symlinks, submodules, sparse
working-directory omissions, incomplete API counts, invalid/mismatched heads,
Git failures, malformed records, and Korean filenames. YAML parsing and every
embedded Bash script's `bash -n` passed.

Readback found that an initial branch update had omitted an existing dispatcher
ref guard. It was restored before opening the PR. The corrected workflow blob
`e9f3d64cca5b3e109c7c9cb093611e7e03f00549` and test blob
`eb090e217e377fc0c07c6dc1dcb08f8d74c85ad3` bind the local verification.

Only the focused source/test snapshot was available locally. This record does
**not** claim the complete central test suite, repository-wide coverage,
actionlint, hosted acceptance, independent approval, or deployment. Those remain
required before protected integration. It also does not claim access to the
original Orca workspace or its uncommitted files.

## Landing and runtime acceptance

First merge this owner repair through normal current-head checks and independent
review. Then obtain a **fresh** consumer workflow execution using the repaired
trusted workflow source. An old run's rerun is not assumed to acquire new source.
For the unchanged content-only consumer head, verify the complete inventory and
explicit not-applicable notice, the correctly expanded required context, and
absence of a fictional scan dispatch. Applicable-code fixtures and independent
security/review checks must still pass. Only then merge the consumer PR.

## References

GitHub. (n.d.). *Error: “No source code was seen during the build.”* GitHub Docs.
Retrieved September 29, 2026, from
https://docs.github.com/en/code-security/reference/code-scanning/troubleshoot-analysis-errors/no-source-code-seen-during-build

GitHub. (2026, September 27). *CodeQL PR, run 36323616223* [Workflow run].
https://github.com/ContextualWisdomLab/korean-writing-skills/actions/runs/36323616223

GitHub. (2026, September 27). *CodeQL Scan Dispatch, run 36343072762* [Workflow run].
https://github.com/ContextualWisdomLab/.github/actions/runs/36343072762
