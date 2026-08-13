# Strix hf-xet hash pin

## Incident and buyer impact

Dependabot rewrote `requirements-strix-ci-hashes.txt` from
`hf-xet==1.5.1` to `1.6.0`. Strix installs that lock with
`pip install --require-hashes`. A version line without every published
platform wheel digest, or a leftover 1.5.1 pin, would either fail closed
or install an unreviewed native wheel.

## Decision

Keep `hf-xet==1.6.0` with all seventeen published SHA-256 digests.
`hf-xet` is Apache-2.0 (permissive SPDX). Do not hand-edit the hashes
file later: regenerate from `requirements-strix-ci.txt`.

CWE-494 forbids downloading code without integrity check (MITRE, 2026).
CWE-829 forbids including functionality from an untrusted control sphere.

## References

MITRE. (2026). *CWE-494: Download of code without integrity check*.
https://cwe.mitre.org/data/definitions/494.html

MITRE. (2026). *CWE-829: Inclusion of functionality from untrusted
control sphere*. https://cwe.mitre.org/data/definitions/829.html

Hugging Face. (n.d.). *hf-xet*. PyPI. Retrieved August 13, 2026, from
https://pypi.org/project/hf-xet/1.6.0/
