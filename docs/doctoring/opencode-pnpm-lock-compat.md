# OpenCode coverage pnpm lock compatibility

검토 기준일: **2026-08-23**

## Decision

OpenCode coverage-evidence honors the repository-owned `packageManager`
pin through Corepack. `--trust-lockfile` is valid only on pnpm 11.3 and
newer (`trustLockfile` landed in pnpm 11.3; Kochan, 2026). pnpm 11.0,
11.1, and 11.2 still reject the flag. Exact trusted-base lock matching
remains mandatory before any offline install. The sandbox never invents a
JavaScript coverage instrumenter when the package did not declare one,
except that a bare `jest` test script still receives Jest's documented
`--coverage` flag.

This keeps LineageWeave and other pnpm 9.x products measurable after
Corepack started activating the repository pin instead of a central
pnpm 11.5.3 binary. A paying reviewer of lineage reconstruction would
otherwise see every frontend head blocked on `Unknown option:
'trust-lockfile'` and, after that, on `vitest --coverage` without
`@vitest/coverage-v8`.

## Root-cause analysis

1. Coverage images now activate the exact `packageManager` from the
   validated base (for LineageWeave, `pnpm@9.15.9`).
2. The install command still passed `--trust-lockfile`, a pnpm 11.3 flag.
   pnpm 9, pnpm 10, and pnpm 11.0–11.2 exit before reading the store.
3. After a successful install, coverage appended `--coverage` to `vitest run`
   even when no coverage provider was declared, so tests never became
   evidence.

The lock-matching gate is unchanged: a PR-added or PR-mutated
`pnpm-lock.yaml` is still refused. `--offline`, `--frozen-lockfile`,
`--ignore-scripts`, and the writable clone of `/opt/pnpm-store` remain
required. Python still never runs `uv sync --project`.

## Remediation

- When `corepack pnpm --version` reports 11.3 or newer (major greater
  than 11, or major 11 with minor 3 or greater), keep `--trust-lockfile`
  so registry attestation lookups stay suppressed for an exact
  trusted-base lock (Kochan, 2026; pnpm, n.d.).
- When the version is below 11.3, omit that flag. pnpm 9, 10, and
  11.0–11.2 already treat `--frozen-lockfile` plus `--offline` as the
  integrity boundary.
- When `package.json` has a test script but no coverage script, coverage
  collector in `scripts.test`, declared provider
  (`@vitest/coverage-v8`, `@vitest/coverage-istanbul`, `c8`, `nyc`,
  `istanbul`), or a bare `jest` runner, run the tests without synthesizing
  an undeclared instrumenter. A `jest` script still receives `--coverage`
  because Jest documents that native flag (Jest, n.d.).

Independent OpenCode, Strix, and Noema review remain authorization
gates. This change does not approve, merge, or weaken hash-pinned
Python or npm installs.

## APA 7th references

GitHub, Inc. (n.d.). *Using a package.json file to specify the package
manager*. GitHub Docs. Retrieved August 23, 2026, from
https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-npm-registry

MITRE. (2026). *CWE-494: Download of code without integrity check*.
https://cwe.mitre.org/data/definitions/494.html

National Institute of Standards and Technology. (2022). *Secure software
development framework (SSDF) version 1.1: Recommendations for mitigating
the risk of software vulnerabilities* (NIST Special Publication 800-218).
https://doi.org/10.6028/NIST.SP.800-218

Jest. (n.d.). *Jest CLI options: --coverage*. Jest Docs. Retrieved
August 23, 2026, from https://jestjs.io/docs/cli#--coverageboolean

Kochan, Z. (2026, May 24). *pnpm 11.3*. pnpm Blog.
https://pnpm.io/blog/releases/11.3

pnpm. (n.d.). *pnpm install*. pnpm Docs. Retrieved August 23, 2026, from
https://pnpm.io/cli/install

Vitest. (n.d.). *Coverage*. Vitest Docs. Retrieved August 23, 2026, from
https://vitest.dev/guide/coverage
