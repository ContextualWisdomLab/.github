# OpenCode coverage wheel compatibility design

## Problem

The organization coverage gate builds a trusted Python 3.14 sandbox and
preflights hash-locked requirements copied from the target pull request's trusted
base commit. The build currently aborts before any pull-request code executes
when a base lock pins a package version that has no compatible binary wheel for
the sandbox interpreter. The observed failure is `atheris==3.0.0`: pip can see a
newer release but cannot select the pinned release while `--only-binary=:all:` is
active.

This state is different from an integrity failure, an unavailable package index,
or malformed lock content. It is a compatibility mismatch between the centrally
selected interpreter and one trusted repository lock. The later networkless
coverage phase already proves whether the skipped lock is actually required to
execute that repository's tests.

## Options considered

### 1. Downgrade the central sandbox interpreter

Pinning the image to Python 3.13 would likely restore an `atheris==3.0.0` wheel.
It would also hide Python 3.14 compatibility defects, weaken coverage for
repositories that support 3.14, and create another fleet-wide upgrade event.
This option is rejected.

### 2. Build a repository-specific Python matrix

The workflow could infer every supported interpreter and build one sandbox per
version. This is more complete but materially increases privileged workflow
complexity, build time, attack surface, and operational cost. It is deferred
until a buyer-visible need justifies the additional system.

### 3. Defer a narrowly proven binary-wheel mismatch

The selected approach recognizes only the paired pip diagnostics that identify
the same exact requirement: both `Could not find a version that satisfies the
requirement ...` and `No matching distribution found for ...` must appear. That
candidate remains visible as a warning and is skipped exactly like an explicit
`requires a different Python` result. Hash mismatches, network failures, empty
output, resolver crashes, and a single ambiguous diagnostic remain fatal.

This preserves fail-closed behavior while preventing one repository's
interpreter-specific fuzzing lock from taking down the organization-wide review
fleet. The later offline coverage execution remains the acceptance gate: if the
missing distribution is necessary, tests or imports still fail.

## Components and data flow

1. `install_base_python_locks._is_deferable_preflight_failure` receives bounded
   pip output from a trusted, hash-enforced, binary-only dry run.
2. A dedicated helper extracts the requirement text from each of the two pip
   diagnostics and returns true only when both are present and identical.
3. The existing installer records the candidate as skipped, prints its source
   and full bounded diagnostic, and continues building the trusted sandbox.
4. The existing networkless test and coverage commands execute against the
   materialized pull-request merge tree and determine final success.

No credentials, pull-request source, workflow command file, database object, or
public module contract changes. The behavior stays inside the central CI module
and remains reusable across independently deployable repositories.

## Testing and acceptance

The regression suite must prove:

- the real two-line `atheris==3.0.0` diagnostic is deferable;
- mismatched requirement names or versions are fatal;
- either diagnostic by itself is fatal;
- existing network, hash, empty-output, and unknown failures remain fatal;
- the installer emits a warning and a successful skipped-count summary for the
  compatible mismatch path;
- the central test suite and exact-head workflow checks pass.

## Evidence

pip documents that `--only-binary=:all:` disables source distributions and that
packages without a compatible binary distribution fail installation. Wheel
compatibility is expressed through Python, ABI, and platform tags. Therefore,
a binary-only dry run can reject a valid trusted pin solely because the central
sandbox does not match that wheel's compatibility tags (Python Packaging
Authority, 2026a, 2026b).

## References

Python Packaging Authority. (2026a). *pip download*. pip documentation.
https://pip.pypa.io/en/stable/cli/pip_download/

Python Packaging Authority. (2026b). *Platform compatibility tags*. Python
Packaging User Guide.
https://packaging.python.org/en/latest/specifications/platform-compatibility-tags/
