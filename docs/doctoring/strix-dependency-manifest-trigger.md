# Strix dependency-manifest quality trigger

## Incident and buyer impact

`requirements-strix-ci-hashes.txt` is executable supply-chain input for the
organization-required Strix gate. The permanent changed-path quality
workflow did not list that file. A Dependabot lock-only pull request could
therefore merge without running the Strix install, policy, shell-regression,
and full-suite contract.

## Decision

Add the exact repository-root manifest path to
`.github/workflows/strix-changed-path-quality-ci.yml` and bind it with
`test_strix_workflow_reruns_when_dependency_manifest_changes`. The same gate
uses production Python 3.13 to perform a hash-enforced dry-run of every pinned
lock entry. It mirrors production's deliberate `--no-deps` boundary because
the reviewed `cryptography==50.0.0` security override is newer than the range
declared by `strix-agent==1.5.3`; every installed entry is still version- and
hash-pinned. The preflight permits source distributions because production
does too, so it does not invent a stricter platform contract. Scanner models,
credentials, timeouts, and result semantics are unchanged.

## References

National Institute of Standards and Technology. (2024). *Cybersecurity
supply chain risk management practices for systems and organizations*
(NIST Special Publication 800-161 Rev. 1).
https://doi.org/10.6028/NIST.SP.800-161r1

Open Source Security Foundation. (2025). *SLSA specification version 1.2*.
https://slsa.dev/spec/v1.2/
