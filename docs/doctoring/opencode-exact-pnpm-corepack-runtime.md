# OpenCode exact pnpm Corepack runtime

## Incident

Exact-head OpenCode coverage runs for `ContextualWisdomLab/LineageWeave` pull
requests 405 and 387 failed before executing repository tests. The trusted-base
materializer correctly retained the frontend declaration
`pnpm@9.15.9+sha512...`, but the generated coverage image accepted only the
literal manifest value `pnpm@11.5.3`. The materialization and execution
contracts therefore disagreed about a value both considered exact.

## Root cause and correction

`materialize_base_javascript_packages.py` admits exact pnpm semantic versions,
including Corepack integrity suffixes. The Docker build subsequently selected a
single separately installed pnpm binary with a literal shell case. Any other
valid exact version failed closed as an unsupported package manager.

Node 24 defines `packageManager` as the exact package-manager version expected
by a project (Node.js Contributors, n.d.-a), and its pinned distribution already
contains Corepack. Corepack reads the nearest `package.json`, selects that exact
version, and verifies an included hash before execution (Node.js Contributors,
n.d.-b). The coverage image now uses that existing runtime instead of installing
a second pnpm binary:

- `COREPACK_HOME=/opt/corepack` retains the integrity-verified package-manager
  cache in the immutable image layer.
- Networked image construction runs `corepack pnpm fetch` only against
  materialized trusted-base package inputs.
- The unprivileged, networkless coverage phase runs all pnpm install, build,
  test, coverage, and docstring package scripts through `corepack pnpm`,
  preserving the declared exact version.
- Existing validated-base lock equality, offline install, disabled lifecycle
  hooks, and writable-store-copy controls remain unchanged.

Corepack documents `name@version` as required and an appended hash as the
recommended supply-chain control; its package-manager dispatch is therefore the
native contract for the repository field already admitted by the materializer
(Node.js Contributors, n.d.-b). This removes duplicate package-manager
installation logic without allowing pull-request-selected executable code into
the networked build boundary.

## Verification

The contract tests were changed first and failed against the literal pnpm
11.5.3 case and the remaining bare `pnpm run` coverage/docstring paths. After
the correction they pass and assert that build-time fetch plus every runtime
install, build, test, coverage, and docstring path uses Corepack.

An amd64 reproduction used the production-pinned Python image and Node archive,
then materialized LineageWeave base commit
`ef6f5a5ffcb467bd935dc1e53acc0029669b0bd7`. Corepack verified and fetched all
244 locked packages for the exact integrity-bearing pnpm 9.15.9 declaration.
The resulting immutable image returned `9.15.9` when invoked as unprivileged uid
65532. No repository record or secret entered the artifact.

For SOC 2 CC8.1 and CSAP change-management evidence, the pull request retains
the failing-run identifiers, root-cause test, exact source revisions, immutable
tool hashes, and rerun results. The change does not alter PII processing.

## References

Node.js Contributors. (n.d.-a). *Modules: Packages*. Node.js v24.18.0
documentation.
https://nodejs.org/download/release/latest-v24.x/docs/api/packages.html#packagemanager

Node.js Contributors. (n.d.-b). *Corepack: Package manager version manager for
Node.js projects*. GitHub. https://github.com/nodejs/corepack
