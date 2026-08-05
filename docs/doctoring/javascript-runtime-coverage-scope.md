# JavaScript runtime coverage scope

## Decision

The central changed-source coverage gate measures JavaScript and TypeScript
application runtime modules, not every executable file that happens to use a
JavaScript-family suffix.

Two bounded non-product categories are excluded from the Istanbul changed-line
contract:

- recognized build and test tool configuration files whose names start with a
  known tool identifier, may include one or more profile segments, and end in
  `.config.<js-family extension>`; and
- repository or module verification commands named `check-*` or `verify-*` in a
  `scripts` directory that is not nested below `src`.

This corrects the concrete Inkspan evidence failure for
`vite.autosave.config.ts`,
`scripts/verify-framework-free-autosave-package.mjs`, and
`scripts/verify-package.mjs`. The product runtime changed by the same pull
request remains subject to complete changed-statement, branch, function, and
line evidence.

## Root cause

Vitest produces coverage for files selected by its coverage configuration and
for modules loaded during the test run. Its current documented defaults exclude
common test files and tool configuration names, and the resolved configuration
also excludes the actual configuration file used for the run. A central gate
that independently reclassifies those files as application runtime creates an
impossible contract: the repository test runner correctly omits the tool file,
but the central post-processor interprets the omission as missing product
instrumentation.

The former classifier recognized only a few exact names such as
`vite.config.ts`. It therefore failed on a valid profile-qualified configuration
name such as `vite.autosave.config.ts`. It also treated bounded package
verification commands as shipped product modules even though those commands are
exercised through separate command-level CI contracts.

## Fail-closed boundary

The correction is deliberately narrower than excluding all configuration or
script paths:

- `src/feature.config.ts` remains application runtime because arbitrary business
  modules may legitimately use a `config` suffix;
- `scripts/serve-package.mjs` remains application runtime because a general
  script may be a shipped CLI or service entry point;
- `src/scripts/verify-session.ts` remains application runtime because a
  `scripts` directory under `src` is part of the product source tree;
- only recognized tool prefixes match the scoped configuration expression; and
- test files, declarations, generated output, fixtures, and dependency trees
  retain their existing explicit exclusions.

A changed runtime file absent from `coverage-final.json` still fails. An
instrumented runtime file still requires every execution unit intersecting the
changed lines to be covered. Global pre-existing coverage remains advisory and
cannot mask changed-code evidence.

## Modular and MSA behavior

The classifier operates on repository-relative POSIX paths and does not assume a
single root package. The same rule therefore supports standalone repositories,
nested packages, and modules imported by Inkspan, naruon, or another Contextual
Wisdom Lab service:

- root `scripts/verify-*` commands are classified consistently;
- nested `packages/<module>/scripts/check-*` commands receive the same bounded
  treatment;
- nested `src` trees retain strict runtime evidence; and
- no package name, pull-request number, tenant, branch, or product-specific
  exception is embedded in the policy.

## Verification contract

The focused regression suite includes the exact Inkspan filenames that triggered
the false positive and proves all of the following:

- profile-qualified Vitest, Vite, and Webpack configuration files are excluded;
- root and nested `check-*` or `verify-*` tooling commands are excluded;
- ordinary product modules, business configuration modules, runtime scripts,
  and `src/scripts` modules remain blocking runtime scope;
- a tooling-only exact Git diff produces an explicit coverage-not-applicable
  decision;
- a changed non-verification runtime script with an empty Istanbul report still
  fails closed;
- unmatched Istanbul records cannot hide the matching changed runtime record;
- malformed location metadata, absolute evidence paths, unrelated JSON files,
  and changed paths with no diff hunks are handled deterministically; and
- the complete central classifier reaches 267 of 267 production statements and
  124 of 124 production branches, with production docstrings present for every
  module and function.

## Exact-head control-plane repair

The first independent OpenCode evidence run on predecessor head
`c216f0cb4d680c381c4389d9b04195d42d1be57d` did not fail in the new JavaScript
classifier. Its merge-tree suite stopped earlier at
`tests/test_codeql_pr_workflow_contract.py::test_codeql_action_steps_use_one_version_per_workflow`
because the protected-base `scheduled-security-scan.yml` used different CodeQL
Action revisions for initialization, analysis, and SARIF upload.

Repair commit `9d43004cbbaa91a8cf477a71e64e1a52176a00ad` aligns all three scheduled phases
to the immutable CodeQL Action v4.37.5 commit
`d1ba80a13dd99fba24a470575428917156a28b43`. This is a central gate-consistency
repair, not an evidence waiver: the runtime classifier, complete changed-code
coverage threshold, Strix dependency floor, reviewer identities, and branch
protection remain unchanged. A fresh review must evaluate the new exact head;
prior-head approval or requested-changes evidence is not transferable.

Repository-wide exact-head CI, security scans, independent review, and branch
protection remain authoritative before merge. No formal Vitest or NIST
conformity is claimed.

## Standards and primary-source traceability

Vitest's current coverage documentation distinguishes V8 and Istanbul providers,
describes JSON coverage reporting, and recommends an explicit source inclusion
boundary. Its versioned configuration reference enumerates default exclusions
for tests, declarations, build output, dependencies, and recognized tool
configuration files. The central rule mirrors that semantic boundary without
copying a mutable glob set wholesale.

NIST SSDF 1.1 requires producers to define, maintain, and verify secure software
development practices and to address root causes so defects do not recur. The
newer SSDF 1.2 initial public draft was reviewed as current guidance, while the
final 1.1 publication remains the normative reference used here.

## References

Booth, H., Ogata, M., Kent, K., Souppaya, M., & Dodson, D. (2025). *Secure
software development framework (SSDF) version 1.2: Recommendations for
mitigating the risk of software vulnerabilities* (NIST Special Publication
800-218 Rev. 1, Initial Public Draft). National Institute of Standards and
Technology. https://doi.org/10.6028/NIST.SP.800-218r1.ipd

Souppaya, M., Scarfone, K., & Dodson, D. (2022). *Secure software development
framework (SSDF) version 1.1: Recommendations for mitigating the risk of software
vulnerabilities* (NIST Special Publication 800-218). National Institute of
Standards and Technology. https://doi.org/10.6028/NIST.SP.800-218

Vitest. (n.d.). *Coverage*. Retrieved August 5, 2026, from
https://main.vitest.dev/guide/coverage

Vitest. (n.d.). *Coverage configuration defaults* (Version 3.2.4) [Computer
software documentation]. GitHub. Retrieved August 5, 2026, from
https://github.com/vitest-dev/vitest/blob/v3.2.4/docs/config/index.md
