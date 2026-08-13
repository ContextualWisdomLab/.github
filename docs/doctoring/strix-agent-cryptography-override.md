# Strix 1.5.3 atomic report persist + cryptography 50 override

검토 기준일: **2026-08-13**

## Incident

The required Strix check on `contextual-orchestrator` (and every other
ruleset consumer of this central workflow) completed a real scan, printed
`Penetration test completed` with a vulnerability list, then exited
non-zero (exit `2`, or `124` after timeout) before the report artifact
was written. `scripts/ci/strix_quick_gate.sh` correctly fail-closed
("No Strix vulnerability report artifact was produced; log-only severity
markers are incomplete evidence"). That gate is working as designed
(ContextualWisdomLab/.github#891) and is not weakened here.

The crash-after-print shape is the 1.0.4 scanner: upstream 1.1.0 added
atomic CSV/MD writes, and 1.4.0+ quit after scan instead of hosting a
local viewer. Latest 1.5.3 keeps both fixes. See
ContextualWisdomLab/.github#952.

A one-line bump is blocked because `strix-agent>=1.4.0` still declares
`cryptography>=48.0.1,<49`, while this repo pins `cryptography==50.0.0`
to stay above CVE-2026-39892 (non-contiguous buffer overflow, fixed in
46.0.7) and to close the PKCS#7 Bleichenbacher-style timing oracle
fixed in 50.0.0 (CVE-2026-69247 / GHSA-g6cj-pr64-35w5). `uv pip compile`
without an override refuses the pair.

## Decision

1. Pin `strix-agent==1.5.3` and keep `cryptography==50.0.0`.
2. Resolve the declared upper bound only at compile time through
   `requirements-strix-ci-overrides.txt` and
   `scripts/ci/compile_strix_ci_lock.sh`.
3. Install the complete hashed lock with
   `pip install --require-hashes --no-deps`. The lock already lists every
   wheel; `--no-deps` prevents pip from re-applying the stale
   `cryptography<49` metadata bound that would otherwise make CI
   uninstallable.
4. Do not scrape console TUI lines as a substitute report. The gate still
   requires a durable artifact.

A live install of this lock on CPython 3.12 imported `strix`, ran
`strix --help`, and loaded `cryptography==50.0.0` together with
`strix-agent==1.5.3`. Strix's only "cryptography" source hit is the
SARIF keyword catalogue, not a PKCS#7 call.

## Trust boundary

- The fail-closed missing-artifact rule is unchanged.
- The override file may contain only `cryptography==50.0.0`.
- Hashes remain required. `--no-deps` is not an unhashed install.
- NVIDIA NIM / OpenCode credentials are untouched.

## Verification contract

`tests/test_strix_agent_cryptography_override.py` proves the input pin,
the singleton override, both versions in the compiled lock, the compile
script flags, the `--no-deps` install line, and that quality CI retriggers
when any of those files change.

## Rollback

If 1.5.3 regresses a required scan, revert the pin to 1.0.4 and the
`--no-deps` install together. Do not drop cryptography 50.0.0 to satisfy
the stale `<49` bound.

## References (APA 7th)

GitHub. (2026). *Cryptography vulnerable to buffer overflow if
non-contiguous buffers were passed to APIs (CVE-2026-39892,
GHSA-p423-j2cm-9vmq)*. GitHub Advisory Database.
https://github.com/advisories/GHSA-p423-j2cm-9vmq

GitHub. (2026). *PKCS#7 decryption timing oracle in pyca/cryptography
(CVE-2026-69247, GHSA-g6cj-pr64-35w5)*. GitHub Advisory Database.
https://github.com/advisories/GHSA-g6cj-pr64-35w5

MITRE. (n.d.). *CWE-208: Observable timing discrepancy*. CWE List.
https://cwe.mitre.org/data/definitions/208.html

National Institute of Standards and Technology. (2026).
*CVE-2026-69247*. National Vulnerability Database.
https://nvd.nist.gov/vuln/detail/CVE-2026-69247

Strix. (2026). *strix-agent 1.5.3 release notes* (atomic CSV/MD writes;
quit after scan). https://github.com/usestrix/strix/releases
