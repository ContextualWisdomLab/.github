# Strix types-requests hash pin

## Incident and buyer impact

Dependabot rewrote `requirements-strix-ci-hashes.txt` from
`types-requests==2.33.0.20260518` to `2.33.0.20260712`. Strix installs
that lock with `pip install --require-hashes`. A version line without
the published SHA-256 digests, or a leftover 20260518 pin, would either
fail closed or install an unreviewed stub wheel.

## Decision

Keep `types-requests==2.33.0.20260712` with both published SHA-256
digests. The package is Apache-2.0 (permissive SPDX). Do not hand-edit
the hashes file later: regenerate from `requirements-strix-ci.txt`.

CWE-494 forbids downloading code without integrity check (MITRE, 2026).
CWE-829 forbids including functionality from an untrusted control sphere.

## References

MITRE. (2026). *CWE-494: Download of code without integrity check*.
https://cwe.mitre.org/data/definitions/494.html

MITRE. (2026). *CWE-829: Inclusion of functionality from untrusted
control sphere*. https://cwe.mitre.org/data/definitions/829.html

Python Software Foundation. (n.d.). *types-requests*. PyPI. Retrieved
August 13, 2026, from https://pypi.org/project/types-requests/2.33.0.20260712/
