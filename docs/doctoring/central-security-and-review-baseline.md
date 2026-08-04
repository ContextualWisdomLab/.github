# Central security and review baseline: evidence record

## Decision

The organization-level `.github` repository owns reusable review, security,
dependency-snapshot, and bounded repair workflows. Product repositories remain
independently operable and consume those controls as modules; they retain their
own application tests, authorization, deployment, release, and data-governance
responsibilities.

The baseline repair makes five controls atomic because they participate in the
same protected-branch decision:

1. CodeQL initialization, analysis, and SARIF upload use one immutable action
   revision within each affected workflow.
2. The central Strix dependency closure removes known-vulnerable package pins
   and remains fully hash-pinned.
3. Trusted-base Python dependency preflight defers only narrowly classified
   incomplete closures, interpreter incompatibility, or binary-unavailable and
   stale pins proven by paired diagnostics for the same exact requirement on a
   reachable index. Every comma-separated alternative must be a concrete,
   conservatively recognized PEP 440 version; blank values, `none`, arbitrary
   prose, mixed version/prose lists, integrity, transport, and unknown errors
   fail closed.
4. Default-branch pushes submit dependency snapshots so pull-request dependency
   review compares a head snapshot with a real base snapshot.
5. Review repair runs once per hour, dispatches at most one bounded repair job,
   and resolves privileged code from the reusable workflow's immutable source
   identity rather than caller data or mutable `main`.

## Standards and current-platform rationale

NIST SSDF version 1.1 is the current final publication; version 1.2 remained a
public draft at the time of this decision. The baseline follows SSDF's final
risk-reduction direction by integrating vulnerability detection, dependency
integrity, repeatable verification, and root-cause regression controls into the
software lifecycle without claiming formal conformance.

The approved SLSA specification is version 1.2. Its source model distinguishes
trusted automation whose identity and codebase cannot be unilaterally
influenced. Immutable action pins, exact-revision dependency materialization,
and called-workflow source binding reduce mutable control-plane inputs in line
with that model without claiming a SLSA level.

GitHub documents that a reusable workflow's ordinary `github` context belongs
to the caller, while reusable-workflow permissions can only remain equal or
become more restrictive through a nested chain. The scheduler therefore binds
its checkout to `job.workflow_repository` and `job.workflow_sha`, rejects caller
or compatibility inputs as executable-source selectors, and omits contents-write
and pull-requests-write permissions.

GitHub also documents that scheduled events can be delayed at the start of an
hour. The hourly heartbeat therefore runs at minute 23. A one-hour same-head
retry floor matches the requested cadence while the one-dispatch budget and
repository-scoped concurrency keep mutation bounded.

GitHub's dependency submission API associates snapshots with commit SHAs and can
submit build-time or SBOM-derived dependencies that static manifest analysis
misses. Snapshotting default-branch pushes supplies the base-side evidence that
pull-request dependency review needs and prevents the entire existing graph from
appearing newly introduced.

## Verification contract

The exact pull-request head must prove:

- one immutable CodeQL revision per affected workflow;
- the central hash lock installs and vulnerability scanners accept it;
- stale-pin deferral requires paired exact-requirement resolver diagnostics and
  a nonempty list in which every alternative is a conservatively valid PEP 440
  version, including epoch, prerelease, postrelease, development, and local
  forms used by pip;
- blank, `none`, arbitrary prose, mixed version/prose lists, single-sided or
  mismatched resolver evidence, integrity, retry, transport, mixed-unknown, and
  unclassified installer failures remain fatal;
- the changed installer has 100% statement and branch coverage and 100%
  production docstrings;
- default-branch snapshot triggers, commit-SHA concurrency, and job-scoped write
  permissions remain pinned by tests;
- hourly cadence, one-hour retry, single dispatch, immutable called-workflow
  source, and least-privilege permissions remain pinned by tests; and
- every current-head security, review, unresolved-thread, and branch-protection
  gate succeeds before merge.

## References

Booth, H., Ogata, M., Kent, K., Souppaya, M., & Dodson, D. (2025). *Secure
software development framework (SSDF) version 1.2: Recommendations for
mitigating the risk of software vulnerabilities* (Initial Public Draft, NIST SP
800-218 Rev. 1). National Institute of Standards and Technology.
https://doi.org/10.6028/NIST.SP.800-218r1.ipd

GitHub. (n.d.). *Reusing workflow configurations*. GitHub Docs. Retrieved August
4, 2026, from
https://docs.github.com/en/actions/reference/workflows-and-actions/reusing-workflow-configurations

GitHub. (n.d.). *Troubleshooting workflows*. GitHub Docs. Retrieved August 4,
2026, from https://docs.github.com/en/actions/how-tos/troubleshoot-workflows

GitHub. (n.d.). *Using the dependency submission API*. GitHub Docs. Retrieved
August 4, 2026, from
https://docs.github.com/en/code-security/how-tos/secure-your-supply-chain/secure-your-dependencies/use-dependency-submission-api

Souppaya, M., Scarfone, K., & Dodson, D. (2022). *Secure software development
framework (SSDF) version 1.1: Recommendations for mitigating the risk of software
vulnerabilities* (NIST SP 800-218). National Institute of Standards and
Technology. https://doi.org/10.6028/NIST.SP.800-218

Supply-chain Levels for Software Artifacts. (2025). *SLSA specification
(version 1.2)*. https://slsa.dev/spec/v1.2/

Supply-chain Levels for Software Artifacts. (2025). *Source: Requirements for
producing source (version 1.2)*.
https://slsa.dev/spec/v1.2/source-requirements
