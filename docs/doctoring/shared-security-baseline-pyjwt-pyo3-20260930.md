# Shared PyJWT and PyO3 security baseline repair

## Status and decision

**Proposed; release HOLD.** The central `.github` repository owns both affected
dependency surfaces, so the repair belongs on a protected-main foundation PR.
It must not be copied into PR #1026, which changes neither lock. The owner repair
must pass exact-head review and hosted security Checks, merge ordinarily, and
then reach #1026 through a non-force merge from protected `main`.

## Exact incident evidence

PR [#1026](https://github.com/ContextualWisdomLab/.github/pull/1026) was observed
at exact head `6f645a73502e159d5a229805afa34868ad9bb851` against protected
`main@37b10243cec3d160ecc9c1be75c71428b160a703`.

- [Security Scan run 36495499815](https://github.com/ContextualWisdomLab/.github/actions/runs/36495499815),
  job `109380628690`, reported PyO3 `0.22.6` in
  `tests/fixtures/coverage-cargo/Cargo.lock`: GHSA-36hh-v3qg-5jq4 (High, 8.0)
  and GHSA-chgr-c6px-7xpp (Medium, 5.5). Both advisories fix the defect in
  PyO3 `0.29.0`; this repair selects and locally verifies `0.29.2`.
- [Python Security run 36495499871](https://github.com/ContextualWisdomLab/.github/actions/runs/36495499871),
  job `109380725819`, reported PyJWT `2.13.0` in
  `requirements-strix-ci-hashes.txt` as affected by CVE-2026-102274. PyJWT
  `2.14.0` is the fixed release.
- The exact #1026 diff changes neither vulnerable file. The same lock bytes
  were present on protected `main`, establishing a shared baseline defect rather
  than a PR-specific regression.

## Root cause and operational scenarios

PyJWT was only a transitive MCP dependency, so the generated Strix lock could
select a newly vulnerable release without an explicit reviewed source pin. A
malformed RSA JWK can raise a plain `ValueError` and abort processing of the
whole JWK Set. An operator can therefore lose otherwise valid signing keys and
fail authentication or review-agent startup because one untrusted key is bad.

The offline Rust coverage fixture intentionally pins exact crate releases, but
its PyO3 pin was not advanced when the two 2026 advisories were published. One
defect permits an out-of-bounds read from iterator methods; the other omits a
required `Sync` bound and permits a data race. Even though this is a test
fixture, the central scanner correctly treats its lock as executable supply
chain material.

## RED to GREEN contract

RED commit `cd84d887` introduced two fail-closed contracts:

1. `requirements-strix-ci.txt` must explicitly select PyJWT `2.14.0`, and the
   generated hash lock must contain the same version.
2. The Rust coverage fixture manifest and lock must both select PyO3 `0.29.2`.

The implementation adds the direct PyJWT input, regenerates the Python 3.13
manylinux hash lock with the repository command, advances the exact PyO3
manifest pin, and regenerates the Cargo lock with Rust `1.97.1`. The
cryptography override remains single-purpose; it does not become a general
security-version overlay.

## Ownership, release, and failure recovery

The fixed-source release workflows consume `requirements-strix-ci-hashes.txt`
from immutable central revisions. This PR repairs the canonical owner bytes but
does not rewrite those workflows to an open branch. After ordinary protected
merge, a separate consumer change must advance their exact source commit and
rerun API/schema, security, SBOM, and provenance evidence. If any exact-head
scanner, build, or independent review fails, the PR remains HOLD and the root
cause is repaired here; no bypass or mutable source reference is permitted.

## Local verification on the repaired tree

- Focused dependency, fixed-source, Maturin asset, and Rust toolchain contracts:
  48 passed, 1 skipped.
- Repository regression suite: 5,160 passed, 11 skipped, 40 subtests passed.
- Rust `1.97.1` `cargo check --locked`: passed for the coverage fixture.
- Python lock regeneration with `uv 0.12.18`, seeded with the existing reviewed
  output, was byte-identical. Input SHA-256 values were `c3812261…` for
  `requirements-strix-ci.txt` and `3b745514…` for the override; the output was
  `8f8318d4…`. A hash-enforced installation loaded PyJWT `2.14.0`. A fresh
  unseeded solve is intentionally not claimed to be byte-identical because it
  may select newer allowed transitive releases.
- `pip-audit`: no known vulnerabilities in the Strix lock. OSV's direct
  `pyo3@0.29.2` query returned no vulnerability records.

No production Python module changes in this repair. The repository-wide
coverage and docstring commands expose separate protected-main baseline debt:
coverage is 99% (178 statements missing) and `interrogate scripts/ci` is 97%
(43 docstrings missing). Those failures are not waived or called green here;
they require their own bounded owner repair before the repository can claim the
100% global gates.

## References

GitHub. (2026, June 12). *Out-of-bounds read in PyO3 iterator methods*
(GHSA-36hh-v3qg-5jq4). GitHub Advisory Database.
https://github.com/advisories/GHSA-36hh-v3qg-5jq4

GitHub. (2026, June 12). *PyO3 missing Sync bound can lead to a data race*
(GHSA-chgr-c6px-7xpp). GitHub Advisory Database.
https://github.com/advisories/GHSA-chgr-c6px-7xpp

Open Source Vulnerabilities. (2026). *CVE-2026-102274: PyJWT RSA JWK Set
availability failure*.
https://osv.dev/vulnerability/CVE-2026-102274

## 2026-10-01 urllib3 audit follow-up

Python Security run `36733279716`, job `109949358063`, found two newly
published vulnerabilities in urllib3 2.7.0: CVE-2026-97687 permits target TLS
policy to weaken or replace HTTPS proxy TLS policy, and CVE-2026-97689 permits
an unbounded chunk-size line to consume memory in streaming clients. Both are
fixed in urllib3 2.8.0. The same vulnerable transitive pin appeared in the
pip-audit and Strix hash locks, so this remains one central security-owner
repair rather than two consumer workarounds.

The repair adds urllib3 2.8.0 to both source inputs and regenerates both locks
with their recorded uv commands. A contract requires exactly one 2.8.0 row in
each source input and generated lock. Comparison against exact predecessor
`d1aa3659fca527a6c7330151f3ab4df3d7578391` shows no unrelated package-version
movement. Repeated compilation produced identical SHA-256 digests, and
pip-audit 2.10.1 reported no known vulnerabilities for either generated lock.
These local results are not merge authority: exact-head hosted security Checks,
terminal authenticated CodeQL evidence, independent approval, and ordinary
protected merge remain required.

## 2026-10-01 PyJWT recursion denial-of-service follow-up

Security Scan run [36741151937](https://github.com/ContextualWisdomLab/.github/actions/runs/36741151937)
found GHSA-42vr-xj54-vc7v /
CVE-2026-101918 in PyJWT 2.14.0. Dependency Review job `109975641239` and OSV
job `109975641271` both rejected that shared Strix lock. An attacker-controlled,
deeply nested unsigned JWT payload can exhaust Python recursion during unverified
payload parsing in `PyJWKClient.get_signing_key_from_jwt`, before key lookup,
and raise an uncaught request-level exception;
the available evidence does not establish a process crash or authentication
bypass. PyJWT 2.15.0 contains the upstream fix.

The canonical-owner repair advances the explicit source pin and generated lock
to 2.15.0. Lock regeneration changes only the PyJWT version and its wheel/sdist
hashes; urllib3 2.8.0, PyO3 0.29.2, and the single-purpose cryptography override
remain unchanged. The existing parity test was first changed to require 2.15.0
and failed against the 2.14.0 source and lock before implementation. Hosted
exact-head Security, CodeQL, independent approval, ordinary protected merge,
and immutable consumer-pin advancement remain release gates.

Local verification used the hosted-workflow Python 3.12 line. The focused
source/lock contract passed 5 tests and the warnings-as-errors repository suite
passed 5,167 tests, 6 skips, and 40 subtests. Repeating the recorded `uv 0.12.18`
compile command was byte-identical at lock SHA-256 `76443a3300d0…`; a
hash-enforced, no-dependency installation loaded PyJWT 2.15.0 and urllib3 2.8.0.
`pip-audit 2.10.1` reported no known vulnerabilities. The repository's existing
97% docstring baseline remains a separate HOLD and is not represented as green.
An independent review found no remaining Critical, Important, or Minor finding
after correcting the advisory's attack-vector wording.

GitHub. (2026). *PyJWT has a denial of service vulnerability via maliciously
crafted JWT token with deeply nested payload* (GHSA-42vr-xj54-vc7v).
https://github.com/jpadilla/pyjwt/security/advisories/GHSA-42vr-xj54-vc7v

