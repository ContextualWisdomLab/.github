# Noema document-reader dependency baseline

## Incident

Security Scan run
[`36773087489`](https://github.com/ContextualWisdomLab/.github/actions/runs/36773087489),
Trivy job `110084194330`, found three medium-severity vulnerabilities in the
generated Noema document-reader lock at exact PR head
`a99784219305d1b6e14cf76f0acea30c5ee45e21`:

- `fast-uri` 3.1.7: CVE-2026-86472 / GHSA-hrr3-gc8f-f4qj;
- `ip-address` 10.7.0: CVE-2026-101911 / GHSA-h3mg-xc3c-68pw; and
- `ip-address` 10.7.0: CVE-2026-101912 / GHSA-j6r3-76f7-8jcv.

The upstream fast-uri advisory fixes the 3.x line in 3.1.8. The ip-address
advisories fix both findings in 10.7.1; this lock selects the first patched 10.7.1
release within the existing `^10.2.0` transitive range.

## Ownership and decision

The vulnerable file is owned by the central `.github` Noema document-reader
runtime, so the repair stays in that owner instead of patching consumer
repositories. The direct manifest is unchanged. `npm update` regenerated only
the two transitive lock entries, including registry URL and integrity digest.

## Verification and remaining gate

`tests/test_noema_document_reader_runtime_dependencies.py` first failed on
3.1.7 and 10.7.0, then passed with exactly one safe entry for each package.
The focused Python context suite passed 14 tests with 2 skipped, `npm ci
--ignore-scripts` reproduced the lock, and `npm audit --omit=dev
--audit-level=moderate` reported zero vulnerabilities. Hosted Security Scan,
CodeQL, independent approval, and ordinary protected merge remain required.
