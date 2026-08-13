# Strix hashed-lock install and pip-audit without pip re-resolution

검토 기준일: **2026-08-13**

## Incident

The required Strix workflow is `pull_request_target`: GitHub runs the **base
branch** copy of `.github/workflows/strix.yml` against the pull-request head
tree. ContextualWisdomLab/.github#961 therefore compiled a complete lock of
`strix-agent==1.5.3` plus `cryptography==50.0.0` (override for CVE-2026-39892
and CVE-2026-69247) and added `--no-deps` to the PR copy of the installer, but
the live required job still executed main's installer:

```text
pip install --require-hashes -r requirements-strix-ci-hashes.txt
```

pip re-applied `strix-agent 1.5.3 depends on cryptography<49 and >=48.0.1`
and exited `ResolutionImpossible`. The same resolver path is what
`python-security.yml` used for every `requirements*.txt` file. pip-audit then
printed `::error::pip-audit reported known-vulnerable Python dependencies`
even though no advisory was returned. A buyer watching the required security
dashboard saw two red X marks on an honest lock.

## Decision

1. Land `--require-hashes --no-deps` on **main's** Strix installer first, with
   no lock change. The current main lock (`strix-agent==1.0.4` +
   `cryptography==50.0.0`) is already a complete hashed set, so `--no-deps`
   does not widen the install. After this lands, a later 1.5.3 lock can
   install under the required base-branch workflow.
2. Audit hashed locks with `pip-audit --disable-pip` via
   `scripts/ci/pip_audit_requirements.py`. Compile-time `*-overrides.txt`
   files and unhashed inputs that already have a `*-hashes.txt` sibling are
   not separate install sets.
3. Do not drop `cryptography==50.0.0` to satisfy the stale `<49` metadata
   bound. Do not treat `ResolutionImpossible` as a vulnerability.

`python-security.yml` is `pull_request` (not `_target`), so the helper takes
effect on the same head that introduces it. Strix still needs this installer
line on the protected base before #961 can go green.

## Trust boundary

- `--no-deps` is not an unhashed install: every wheel remains hash-pinned.
- `--disable-pip` still queries the advisory database for every pinned name
  and version; it only skips pip's metadata resolver.
- NVIDIA NIM / OpenCode review-agent credentials are untouched.
- No operational PII is masked.

## Verification contract

`tests/test_pip_audit_requirements.py` reconstructs the #961 lock shape and
requires `--disable-pip` for that file, a skip for the override/input pair,
and the `--no-deps` installer line on `strix.yml`. A `*-hashes.txt` name
or a lone `--require-hashes` directive without `--hash=` is not treated
as a complete lock. A mixed file with one hashed line beside unhashed
packages also stays on the resolver path. Discovery skips `.venv` trees.
Materialize accepts a requirements include only as a two-token
``-r``/``--requirement`` form whose target is a normalized relative POSIX
lock path with no ``.`` or ``..`` components, so a dotted include cannot
enter the trusted build context (CWE-22; MITRE, 2026).

## References (APA 7th)

MITRE. (2026). *CWE-22: Improper limitation of a pathname to a restricted
directory ('Path Traversal')*. https://cwe.mitre.org/data/definitions/22.html

GitHub. (2026). *Cryptography vulnerable to buffer overflow if
non-contiguous buffers were passed to APIs (CVE-2026-39892,
GHSA-p423-j2cm-9vmq)*. GitHub Advisory Database.
https://github.com/advisories/GHSA-p423-j2cm-9vmq

GitHub. (2026). *PKCS#7 decryption timing oracle in pyca/cryptography
(CVE-2026-69247, GHSA-g6cj-pr64-35w5)*. GitHub Advisory Database.
https://github.com/advisories/GHSA-g6cj-pr64-35w5

National Institute of Standards and Technology. (2026).
*CVE-2026-69247*. National Vulnerability Database.
https://nvd.nist.gov/vuln/detail/CVE-2026-69247

pypa. (2025). *pip-audit: ``--disable-pip`` (hashed requirements / ``--no-deps``
only)*. https://github.com/pypa/pip-audit

Python Packaging Authority. (n.d.). *Hash-checking mode*. pip documentation.
https://pip.pypa.io/en/stable/topics/secure-installs/#hash-checking-mode
