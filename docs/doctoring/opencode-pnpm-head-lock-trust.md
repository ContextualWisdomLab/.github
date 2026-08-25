# OpenCode coverage validated head pnpm locks

검토 기준일: **2026-08-25**

## Decision

OpenCode coverage-evidence now trusts a PR-mutated `pnpm-lock.yaml` only when
the trusted materializer recorded that exact lock blob from the validated HEAD
revision. The sandbox keeps three integrity boundaries and adds a fourth:

1. The coverage source artifact must hash-match the validated `PR_HEAD_SHA`
   lock (tamper evidence between artifact download and use).
2. An unchanged base lock (base blob equals head blob) remains trusted exactly
   as before.
3. A head-mutated lock is trusted only when
   `/opt/javascript-package-locks/manifest.json` records
   `source`, `revision_sha == PR_HEAD_SHA`, and `lock_blob` for this project —
   proving the offline store was prefetched from the same hash-bounded lock at
   image build time.
4. Before materialization, `validate_head_pnpm_lock` fails closed unless every
   package entry pins one SHA-512 SRI, every tarball URL is an HTTPS
   `registry.npmjs.org` URL without userinfo, port, query, or fragment, and any
   workspace link target is a relative in-project directory. VCS or file
   sources are refused.

The npm path already followed this pattern through
`validate_head_npm_lock`; the pnpm path now mirrors it. `--offline`,
`--frozen-lockfile`, and lifecycle-hook suppression remain mandatory, so a
mutated lock can never fetch anything outside the store that was verified
against the registry's own integrity metadata during image build (npm, n.d.;
pnpm, n.d.).

## Root-cause analysis

1. The previous gate required base blob == head blob == worktree blob for
   every pnpm project. Any dependency-raising pull request necessarily mutates
   the lockfile, so such PRs failed coverage-evidence with "Current pnpm lock
   differs from the validated base" regardless of content quality.
2. The failure was not hypothetical: ContextualWisdomLab/inkspan#373 (a
   transitive security-floor raise for fast-uri, nanoid, and postcss) carried
   fully green repository-owned checks but could never satisfy this gate,
   leaving the security fix unmergeable while Dependabot alerts stayed open.
3. The image build already consumed strictly registry/hash-bounded inputs from
   the live-validated HEAD (`materialize_base_javascript_packages.py --head-sha`),
   so refusing head-mutated pnpm locks added no integrity guarantee that the
   build did not already enforce; it only blocked legitimate dependency work.

## Remediation

- Materializers validate changed head pnpm locks with the same fail-closed
  posture as npm locks before anything enters the networked build context.
- The sandbox consults the trusted manifest record instead of refusing every
  mutation, keeping tamper evidence against `PR_HEAD_SHA`.
- Repositories regain the ability to ship audited dependency updates through
  reviewed pull requests instead of forcing direct-to-main writes.

Independent OpenCode, Strix, and Noema review remain authorization gates. This
change does not approve, merge, or weaken hash-pinned Python installs, registry
allowlists, or the networkless PR sandbox.

## APA 7th references

MITRE. (2026). *CWE-494: Download of code without integrity check*.
https://cwe.mitre.org/data/definitions/494.html

National Institute of Standards and Technology. (2022). *Secure software
development framework (SSDF) version 1.1: Recommendations for mitigating the
risk of software vulnerabilities* (NIST Special Publication 800-218).
https://doi.org/10.6028/NIST.SP.800-218

npm, Inc. (n.d.). *Package lock specification: integrity fields*. npm Docs.
Retrieved August 25, 2026, from https://docs.npmjs.com/cli/v10/configuring-npm/package-lock-json

Open Worldwide Application Security Project. (2025). *OWASP Top 10: A06
— vulnerable and outdated components*. https://owasp.org/Top10/A06_2021-Vulnerable_and-Outdated-Components/

pnpm. (n.d.). *Settings: lockfile and frozen-lockfile*. pnpm Docs.
Retrieved August 25, 2026, from https://pnpm.io/settings
