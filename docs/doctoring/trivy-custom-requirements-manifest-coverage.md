# Trivy custom requirements manifest coverage

Status: `active_pr` until the required and periodic workflows are present on
protected `main`; thereafter `implemented_on_protected_main`.

## Root cause and repair

Trivy's default pip analyzer does not discover every generated or purpose-named
`requirements-*.txt` file. A Naruon merge-ref scan using Trivy 0.74.0 found four
dependency manifests with default discovery and eleven after adding the pip
pattern. The expanded scan exposed `CVE-2026-69244` in
`requirements-strix-ci-hashes.txt`; the installed aiohttp 3.14.1 is affected and
3.14.3 is the patched release.

Both central filesystem-scan owners set
`TRIVY_FILE_PATTERNS=pip:requirements-.*\.txt` directly on the pinned Trivy
action step. This is trusted workflow configuration, not a configuration file
from the repository being scanned. It adds custom pip manifest discovery while
retaining Trivy's default detection. The required PR scan and the scheduled
default-branch backstop therefore use the same manifest boundary without adding
a workflow, job, step, or scanner invocation.

The severity set, unfixed-vulnerability policy, zero scanner exit used to
preserve SARIF, hard-fail SARIF parser, and upload behavior are unchanged.

## Verification boundary

The regression contract requires the trusted environment setting on both
existing action calls. A local Trivy 0.74.0 fixture scan separately demonstrates
that `requirements-strix-ci-hashes.txt` is absent from default results and
present when the pattern is set. Protected-main and consumer merge-ref runs are
still required runtime evidence.

## References

Aqua Security. (2026). *Filtering and custom file handling*. Trivy
documentation v0.74.0.
https://github.com/aquasecurity/trivy/blob/v0.74.0/docs/guide/configuration/skipping.md

aiohttp project. (2026). *Out-of-bounds heap read in C HTTP parser when
constructing an error message for malformed responses* (GHSA-cq5v-8q36-5273;
CVE-2026-69244).
https://github.com/aio-libs/aiohttp/security/advisories/GHSA-cq5v-8q36-5273
