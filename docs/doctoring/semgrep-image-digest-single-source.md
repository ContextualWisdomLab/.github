# Semgrep image digest single source

## Incident and buyer impact

The central Semgrep job logged one image tag/digest pair and executed
another. A buyer or auditor reconstructing the scan could not prove the
logged scanner was the scanner that ran. A partial local digest then
surfaced as an ambiguous image-manifest failure instead of a fail-closed
pin error.

## Decision

Keep Semgrep OSS 1.169.0 at one job-level `SEMGREP_IMAGE` value. Validate
the complete `semgrep/semgrep@sha256:<64-hex>` form, inspect that exact
manifest, and pass the same value to `docker run`. Scan policy, SARIF
handling, metrics-off, and `--error` remain unchanged.

## References

National Institute of Standards and Technology. (2017). *Application
container security guide* (NIST Special Publication 800-190).
https://doi.org/10.6028/NIST.SP.800-190

The Linux Foundation. (2023). *SLSA: Supply-chain levels for software
artifacts* (Version 1.0). https://slsa.dev/spec/v1.0/
