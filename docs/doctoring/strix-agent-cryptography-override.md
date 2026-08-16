# Strix 1.5.3 atomic report persist + cryptography 50 override

검토 기준일: **2026-08-16**

## Incident

The required Strix check is the central `pull_request_target` /
`repository_dispatch` workflow in this repository. On current `main`
(`c47afc2dc68488292c1db7c9d6f82dcd5360f181`) consumer runs still install
`strix-agent==1.0.4` with `cryptography==50.0.0`. Recent failures that
were re-read for this increment, not only ContextualWisdomLab/.github#952:

| Consumer | Run | Observed terminal shape |
|---|---|---|
| ContextualWisdomLab/mightyETL#315 | [31950271564](https://github.com/ContextualWisdomLab/.github/actions/runs/31950271564) / job 95172565509 | `Tool execute not found in agent strix`, then `No Strix vulnerability report artifact was produced; log-only severity markers are incomplete evidence` |
| ContextualWisdomLab/.github#1023 | [31952135549](https://github.com/ContextualWisdomLab/.github/actions/runs/31952135549) / job 95177171349 | `Penetration test completed` / `Vulnerabilities MEDIUM: 1`, then exit 2 and `Strix report artifacts emitted warning/fatal/denied/timeout output; failing closed` |
| ContextualWisdomLab/noema#392 | [31950935010](https://github.com/ContextualWisdomLab/.github/actions/runs/31950935010) | required `strix` red on the same 1.0.4 lock |

The fail-closed missing-artifact rule in `scripts/ci/strix_quick_gate.sh`
(ContextualWisdomLab/.github#891) is working as designed and is not
weakened here. Console TUI lines such as `Vulnerabilities MEDIUM: 1` are
not a passing report.

The crash-after-print shape is the 1.0.4 scanner. Upstream 1.1.0 added
atomic CSV/MD writes, and 1.4.0+ quit after scan instead of hosting a
local viewer. Latest PyPI release remains `strix-agent==1.5.3` and still
declares `cryptography>=48.0.1,<49` (usestrix/strix#859, Intel macOS
universal2 wheel). See ContextualWisdomLab/.github#952.

A one-line bump is blocked because `uv pip compile` without an override
refuses `strix-agent==1.5.3` + `cryptography==50.0.0`. Cryptography 50.0.0
is the floor that closes CVE-2026-69247 (PKCS#7 EnvelopedData
Bleichenbacher-style timing/error oracle in `pkcs7_decrypt_der` /
`pkcs7_decrypt_pem` / `pkcs7_decrypt_smime`, introduced in 44.0.0). It
also sits above CVE-2026-39892 (non-contiguous buffer overflow, fixed in
46.0.7).

## Decision

1. Pin `strix-agent==1.5.3` and keep `cryptography==50.0.0`. Materialize
   only exact SHA-256 pins or a bounded relative `-r` include; a lone
   `--require-hashes` line is not lock evidence.
2. Resolve the declared upper bound only at compile time through
   `requirements-strix-ci-overrides.txt` and
   `scripts/ci/compile_strix_ci_lock.sh`.
3. Install the complete hashed lock with
   `pip install --require-hashes --no-deps`. The lock already lists every
   wheel; `--no-deps` prevents pip from re-applying the stale
   `cryptography<49` metadata bound that would otherwise make CI
   uninstallable. Immediately after install, the workflow fail-closes
   unless `importlib.metadata` reports `strix-agent==1.5.3` and
   `cryptography==50.0.0`.
4. Do not scrape console TUI lines as a substitute report. The gate still
   requires a durable artifact and still fail-closes on warning / fatal /
   denied / timeout report signals.

A live `pip`/`uv` install of this hashed lock with `--require-hashes
--no-deps` imported `strix`, ran `strix --help` (including the
non-interactive “exits on completion” path), and loaded
`cryptography==50.0.0` together with `strix-agent==1.5.3` on CPython
3.12.3 and 3.13.15.

## Trust boundary

- The fail-closed missing-artifact rule is unchanged.
- The override file may contain only `cryptography==50.0.0`.
- Hashes remain required. `--no-deps` is not an unhashed install.
- NVIDIA NIM / OpenCode credentials are untouched. This path never uses
  `COPILOT_GITHUB_TOKEN`.

## Verification contract

`tests/test_strix_agent_cryptography_override.py` proves the input pin,
the singleton override, both versions in the compiled lock, the compile
script flags, the `--no-deps` install line, the post-install
`strix-agent==1.5.3` / `cryptography==50.0.0` metadata check, and that
quality CI retriggers when any of those files change.

## Rollback

If 1.5.3 regresses a required scan, revert the pin to 1.0.4 and the
`--no-deps` install together. Do not drop cryptography 50.0.0 to satisfy
the stale `<49` bound.

## After merge

Consumer required `strix` checks read this workflow from protected
`main`. After this lands, a new same-head scan installs 1.5.3, persists
the report directory, and lets the existing gate judge that artifact.
Findings at or above `STRIX_FAIL_ON_MIN_SEVERITY` still fail the check.
A completed scan with no threshold finding can go green.

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
