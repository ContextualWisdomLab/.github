# Strix google-cloud-bigquery hash pin

## Incident and buyer impact

Dependabot rewrote `requirements-strix-ci-hashes.txt` from
`google-cloud-bigquery==3.42.2` to `3.43.0`. Strix installs that lock
with `pip install --require-hashes`. A version line without the published
SHA-256 digests, or a leftover 3.42.2 pin, would either fail closed or
install an unreviewed wheel.

## Decision

Materialize accepts only exact SHA-256 pins or a bounded relative `-r` include; a lone `--require-hashes` line is not lock evidence.

Keep `google-cloud-bigquery==3.43.0` with both published SHA-256
digests. The package is Apache-2.0 (permissive SPDX). Do not hand-edit
the hashes file later: regenerate from `requirements-strix-ci.txt`.

CWE-494 forbids downloading code without integrity check (MITRE, 2026).
CWE-829 forbids including functionality from an untrusted control sphere.

## References

MITRE. (2026). *CWE-494: Download of code without integrity check*.
https://cwe.mitre.org/data/definitions/494.html

MITRE. (2026). *CWE-829: Inclusion of functionality from untrusted
control sphere*. https://cwe.mitre.org/data/definitions/829.html

Google LLC. (n.d.). *google-cloud-bigquery*. PyPI. Retrieved August 13,
2026, from https://pypi.org/project/google-cloud-bigquery/3.43.0/
