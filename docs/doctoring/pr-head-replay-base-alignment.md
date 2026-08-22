# PR-head replay guard: protected-base alignment

## Observed failure

LineageWeave pull request 258 exact head
`6dc040c6b3ea0bfc4424bb7afb11b8afd7205d77` failed central OpenCode coverage
run `32528869351`. The replay guard found that five commits after the newest
protected-base-descended merge removed three files, including
`tests/test_lineage_contract.py`.

The exact protected base
`ef6f5a5ffcb467bd935dc1e53acc0029669b0bd7` already omitted both that test and
its same-subject runtime module. The head also omitted both. No path had been
restored to pre-merge content, the head did not replay an earlier tree, and the
three-file delta stayed below the conservative bulk-replay threshold. The
test-regression signal nevertheless treated every post-merge test deletion as
protected-base evidence loss.

## Decision and security boundary

The guard now distinguishes one base-alignment case from an evidence
regression. A test absent from the exact protected base is not reported as
regressed only when a non-test file with the same logical subject and language
suffix is deleted in the same post-merge range and that source is also absent
from the protected base. This admits removal of a feature-only source/test pair
that aligns the head with the protected branch without letting a same-named
documentation deletion excuse a code-test deletion.

The following cases remain blocking:

- a test or same-subject source present on the protected base is removed;
- a feature-only test is removed while its source remains;
- a retained test file loses declared test cases without a replacement test
  file;
- the head exactly replays a pre-merge tree, restores a path to its pre-merge
  content, or crosses the conservative bulk-deletion thresholds.

This boundary follows NIST SSDF's root-cause and verification practices while
preserving GitHub's guidance that privileged pull-request workflows must treat
pull-request state as untrusted input. The decision is based only on immutable
Git objects from the validated base, merge anchor, and head; no pull-request
code executes during classification.

## Verification

- A new Git-history regression reproduces a feature-only source/test pair,
  merges the exact protected base, removes the pair, and requires a passing
  replay decision.
- Existing regressions continue to require failure for protected-base source
  and test removal, test-only deletion, weakened retained tests, exact replay,
  targeted unmerge, and bulk deletion.
- The patched guard passes against the observed LineageWeave base/head pair and
  reports no regressed protected-base test path.
- The focused replay-guard suite, complete central Python quality suite,
  docstring coverage, workflow validation, and diff hygiene run on the final
  tree.
- The project-local uv environment declares pip because the existing bounded
  include regression invokes `python -m pip` for its hash preflight; verification
  no longer depends on an unrecorded manual venv seed.

## References

GitHub. (n.d.). *Secure use reference*. GitHub Docs. Retrieved August 22, 2026,
from https://docs.github.com/en/actions/reference/security/secure-use

Souppaya, M., Scarfone, K., & Dodson, D. (2022). *Secure software development
framework (SSDF) version 1.1: Recommendations for mitigating the risk of
software vulnerabilities* (NIST Special Publication 800-218). National
Institute of Standards and Technology. https://doi.org/10.6028/NIST.SP.800-218
