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
uses production Python 3.13 to perform a binary-only, hash-enforced dry-run of
the complete lock, so a corrupt, incomplete, or incompatible manifest cannot
pass merely because it triggered the workflow. Scanner models, credentials,
timeouts, and result semantics are unchanged.

## References

National Institute of Standards and Technology. (2024). *Cybersecurity
supply chain risk management practices for systems and organizations*
(NIST Special Publication 800-161 Rev. 1).
https://doi.org/10.6028/NIST.SP.800-161r1

The Linux Foundation. (2023). *SLSA: Supply-chain levels for software
artifacts* (Version 1.0). https://slsa.dev/spec/v1.0/
