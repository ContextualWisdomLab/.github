# Noema document-reader npm security refresh

**Status:** Proposed on `ContextualWisdomLab/.github#2543`; hosted exact-head
Checks and qualifying independent approval remain required.

## Failure evidence and root cause

Security Scan run
[`36770011020`](https://github.com/ContextualWisdomLab/.github/actions/runs/36770011020),
job `110073743404`, scanned exact PR head
`f79a617aef6eca2e83f822a0014130372ffa54ef` and reported three findings in
`scripts/ci/noema-document-reader/package-lock.json`:

- `fast-uri` `3.1.7` — CVE-2026-86472 / GHSA-hrr3-gc8f-f4qj;
- `ip-address` `10.7.0` — CVE-2026-101911 / GHSA-h3mg-xc3c-68pw; and
- `ip-address` `10.7.0` — CVE-2026-101912 / GHSA-j6r3-76f7-8jcv.

The first Trivy registry mirror returned `BLOB_UNKNOWN`, but Trivy then
downloaded its database successfully from GHCR and produced the three SARIF
findings. The registry-mirror error therefore is not the job's causal failure.
GitHub's reviewed advisories identify `fast-uri` `3.1.8` and `ip-address`
`10.7.1` as the first fixed releases in the installed major lines. The direct
Noema reader packages were unchanged; permissive transitive ranges selected
the newly disclosed vulnerable releases.

## RED → GREEN repair

The existing hosted-reader contract was extended first to require the two
non-vulnerable versions. It failed against the published lock (`3.1.7` versus
required `3.1.8`). The repair adds exact npm overrides, regenerates the lock,
and changes no other dependency version. This keeps source intent and generated
lock evidence together instead of hand-editing integrity data.

Local evidence on the repaired tree:

- focused contract: `1 passed`;
- `npm ci --ignore-scripts --omit=dev --no-audit --no-fund`: success, 108
  packages installed; and
- `npm audit --package-lock-only --omit=dev --audit-level=moderate`: `0`
  vulnerabilities.

The repair does not suppress a finding, lower severity, bypass scripts, relax
a gate, or claim that local audit output authorizes merge. Repair parent
`acd0fbbc54c37dc8558eaea026f38eabf7d1243d` published the reviewed lock
updates: Security Scan and SAST passed, while CodeQL remained fail-closed
pending. The live exact head must complete fresh protected Checks and receive
an independent approval before ordinary integration.

## References

GitHub. (2026a). *fast-uri vulnerable to inconsistent host case normalization
via percent-encoded octets* (GHSA-hrr3-gc8f-f4qj).
https://github.com/fastify/fast-uri/security/advisories/GHSA-hrr3-gc8f-f4qj

GitHub. (2026b). *ip-address: Address6 builds a parse diagnostic proportional
to the input with no length bound, allowing a single long string to stall or
crash the process* (GHSA-h3mg-xc3c-68pw).
https://github.com/beaugunderson/ip-address/security/advisories/GHSA-h3mg-xc3c-68pw

GitHub. (2026c). *ip-address: isInSubnet() and isHostInSubnet() compare
addresses of different families as if they shared an address space, allowing
an allowlist check to admit an address outside its range*
(GHSA-j6r3-76f7-8jcv).
https://github.com/beaugunderson/ip-address/security/advisories/GHSA-j6r3-76f7-8jcv

National Institute of Standards and Technology. (2022). *Secure software
development framework (SSDF) version 1.1: Recommendations for mitigating the
risk of software vulnerabilities* (NIST SP 800-218).
https://doi.org/10.6028/NIST.SP.800-218
