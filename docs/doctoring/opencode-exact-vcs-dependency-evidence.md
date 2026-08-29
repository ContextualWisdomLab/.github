# OpenCode exact VCS dependency evidence

## Decision

The OpenCode coverage image may expose a Python dependency directly from source
only when the validated base branch's frozen `uv.lock`, or a changed exact-head
`uv.lock` project selected for coverage, names an HTTPS GitHub repository owned
by `ContextualWisdomLab` and a full 40-character Git commit. Registry
dependencies remain exact-version, SHA-256-pinned `pip` installs.

The trusted materializer separates those two dependency classes. Unchanged
projects remain base-bound; changed or newly added projects are exported from
the exact HEAD with the same isolated frozen/offline exporter. The networked,
secret-free image build fetches each approved source revision, verifies that
`FETCH_HEAD` and the checked-out `HEAD` equal the locked commit, removes Git
metadata, verifies a normalized package import root, and records only that
repository root or its `src` directory in a Python path file. It does not run
dependency build or installation code. The pull-request tree still runs later
with no network and no credentials.

## Root cause

LineageWeave's protected base lock contains RankWeave at its immutable release
commit because the current RankWeave release is not yet available from PyPI.
`uv export` therefore emitted one exact VCS requirement alongside fully hashed
registry requirements. The former materializer rejected the complete export,
so OpenCode never reached tests and repeatedly requested changes despite the
product's current-head tests passing.

## Safety boundary

- Symbolic refs, abbreviated commits, non-HTTPS schemes, credentials, ports,
  query strings, fragments, subdirectories, and repositories outside the exact
  organization origin fail closed.
- Duplicate references to one repository must resolve to one commit; conflicting
  revisions fail before the image build.
- Only metadata read from the validated base SHA or a changed project in the
  exact validated HEAD can select a dependency. Pull request source cannot
  modify the networked image build inputs outside those immutable revisions.
- Source dependencies are import-only. No `pip install`, PEP 517 backend, setup
  hook, or dependency lifecycle script runs while the network is available.
- The source repository must be publicly fetchable without credentials, expose
  the normalized top-level import package directly or under `src`, and remain a
  pure-Python leaf dependency. Private repositories, environment-marked VCS
  requirements, namespace/layout aliases, installed-distribution metadata,
  entry points, compiled extensions, and registry packages that require the VCS
  distribution fail closed instead of expanding the secret-free build boundary.
- The checkout roots and path file are explicitly world-readable so the later
  networkless coverage container can run as UID 65532 independently of the
  image builder's umask.
- This records exact source inputs for a test image; it does not claim a SLSA
  build level or substitute for upstream package publication and attestation.

These controls follow pip's recommendation to use full VCS commit hashes and
SLSA 1.2's treatment of Git revisions as immutable identifiers, while retaining
the isolated, ephemeral test execution boundary (Python Packaging Authority,
2026c; Supply-chain Levels for Software Artifacts, 2025). They also support the
SSDF practice of preserving dependency provenance and preventing recurrence of
toolchain failures (Souppaya et al., 2022).

## Verification

Regression tests cover the real LineageWeave export shape, rejection of unsafe
VCS forms, conflicting commits, deterministic manifests, exact-fetch workflow
commands, and the existing registry hash contract. Before source-only Python
path publication, the image build requires exactly one normalized root, a
regular `__init__.py` for packages, and no symbolic links, compiled extensions,
or installed distribution metadata. Namespace, alias/ambiguous, and native
layouts therefore fail the build. The central Python quality workflow retains
100% statement/branch and docstring coverage.

## Independent root lock environments

An exact-base coverage run for `contextual-orchestrator` exposed four
root-level lock candidates: two independently complete application/tool locks
and two security-tool fragments whose transitive `pip` dependency was not
pinned and hashed. The installer correctly identified the incomplete
candidates, but then treated every file sharing the repository root as one
supplement group. That synthetic environment combined mutually exclusive
versions of `rpds-py`, so a valid application lock could not reach the
networkless test phase.

Directory co-location is not a dependency relationship. The installer now
recovers only an unambiguous directory containing exactly two candidates and at
least one incomplete candidate. Directories containing more root locks require
an explicit requirements-file include graph; absent that evidence, complete
locks install independently and incomplete closures remain skipped. This keeps
pip's all-or-nothing hash rule intact rather than weakening `--require-hashes`
or choosing a dependency version locally. The boundary follows pip's defined
`-r` include mechanism and its requirement that every dependency in hash mode
be pinned and hashed (Python Packaging Authority, 2026a, 2026b). It also
supports SSDF verification of third-party components and secure build
configuration (Souppaya et al., 2022).

The regression contract uses four root candidates and fails if the installer
combines any of them. A Linux Python 3.14 replay against the exact protected
base materialization preflighted all four, installed the two independently
complete closures, skipped the two incomplete closures with their bounded root
causes, and exited successfully.

## References

Python Packaging Authority. (2026a). *Requirements file format*. pip
documentation v26.2.1.
https://pip.pypa.io/en/stable/reference/requirements-file-format/

Python Packaging Authority. (2026b). *Secure installs*. pip documentation
v26.2. https://pip.pypa.io/en/stable/topics/secure-installs/

Python Packaging Authority. (2026c). *VCS support*. pip documentation v26.2.
https://pip.pypa.io/en/stable/topics/vcs-support/

Souppaya, M., Scarfone, K., & Dodson, D. (2022). *Secure software development
framework (SSDF) version 1.1: Recommendations for mitigating the risk of
software vulnerabilities* (NIST Special Publication 800-218). National
Institute of Standards and Technology. https://doi.org/10.6028/NIST.SP.800-218

Supply-chain Levels for Software Artifacts. (2025). *SLSA specification
(Version 1.2)*. https://slsa.dev/spec/v1.2/
