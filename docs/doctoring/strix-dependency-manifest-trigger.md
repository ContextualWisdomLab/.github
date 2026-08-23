# Strix dependency-manifest quality trigger

## Incident and buyer impact

`requirements-strix-ci-hashes.txt` is executable supply-chain input for the
organization-required Strix gate. The permanent changed-path quality
workflow did not list that file. A Dependabot lock-only pull request could
therefore merge without running the Strix policy, shell-regression, security,
and full-suite contracts.

## Decision

Add the exact repository-root manifest path to
`.github/workflows/strix-changed-path-quality-ci.yml` and bind it with
`test_strix_workflow_reruns_when_dependency_manifest_changes`. Do not pass the
pull-request-controlled lock to `pip` in this job. A hash-matching source
distribution can execute its PEP 517 build backend while pip prepares metadata,
even for `--dry-run --no-deps --require-hashes`. Hosted Strix run `32643804284`
reproduced that execution path at the exact pull-request head. Requiring wheels
is not an equivalent repair because the production closure includes packages
without a compatible wheel. Production resolution therefore remains inside the
trusted default-branch Strix boundary, while every lock change still triggers
the permanent policy, regression, and security review gates. Scanner models,
credentials, timeouts, and result semantics are unchanged.

## References

National Institute of Standards and Technology. (2024). *Cybersecurity
supply chain risk management practices for systems and organizations*
(NIST Special Publication 800-161 Rev. 1).
https://doi.org/10.6028/NIST.SP.800-161r1

Open Source Security Foundation. (2025). *SLSA specification version 1.2*.
https://slsa.dev/spec/v1.2/
