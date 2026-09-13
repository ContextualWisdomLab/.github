# Product performance evidence attestation

## Problem

Product performance acceptance needs two separate decisions that must not be collapsed into one status:

1. whether a measured result, runtime observation, and right-cleared fixture are the exact bytes produced by an authorized CWL workflow run; and
2. whether those bytes satisfy the product's latency, production-equivalence, scientific-validity, and data-rights acceptance policy.

A product-local SHA-256 token cannot establish the first decision when the caller can replace both the evidence and the token. Likewise, a generic `PASS` emitted by the central verifier would incorrectly imply the second decision.

This boundary was introduced from `ContextualWisdomLab/Orgmetra#316/#317` and is owned centrally by `.github#2162`. HR-domain semantics, workload construction, right-cleared data, resource/cleanup observations, and the p95 policy remain with Orgmetra.

## Decision

`.github/workflows/product-performance-attestation.yml` is the organization-owned reusable signer. Callers must pin it by a full commit SHA. The workflow accepts exact caller/source and evidence identities, but it does not trust those inputs on their own.

Before any caller artifact is used, both jobs:

- resolve the called reusable workflow identity from GitHub Actions OIDC `job_workflow_ref` and `job_workflow_sha`;
- require a GitHub-hosted signer runner;
- require the caller repository to be in the `ContextualWisdomLab` organization;
- require the supplied source repository and SHA to equal the caller `GITHUB_REPOSITORY` and `GITHUB_SHA`;
- re-read immutable artifact ID, name, digest, workflow-run identity, expiry state, and compressed size from the GitHub REST API.

The central signer attests **origin and byte integrity only**. The predicate is `https://contextualwisdomlab.org/attestations/product-performance/v1` and explicitly records that it does not prove latency-threshold success, production equivalence, fixture scientific validity, or fixture right clearance. Structural verification is recorded as `verification_result: VALID`; the central layer must not emit a generic performance `PASS`.

## Bounded inert artifact handling

The artifact is bounded before extraction. GitHub's artifact metadata `size_in_bytes` must be positive and no greater than 300 MiB. The ZIP is then downloaded from the immutable artifact-ID endpoint with curl's transfer-size limit, rechecked by filesystem size, and hashed. Its SHA-256 must equal the GitHub artifact digest before any member is decompressed.

`materialize_product_performance_artifact.py` then treats the archive as hostile inert data:

- exactly three distinct root-level files are allowed: result, runtime evidence, and fixture;
- directories, traversal/nested paths, duplicate names, symlinks/non-regular UNIX entries, encryption, and compression other than stored/deflated are rejected;
- declared member sizes are bounded before decompression: 16 MiB result, 16 MiB runtime evidence, 256 MiB fixture;
- decompressed bytes are streamed with independent counters so central-directory declarations alone cannot bypass the limits;
- extraction occurs only into a newly created private directory; `ZipFile.extract()` and `extractall()` are not used;
- the existing strict verifier then re-hashes each materialized file, requires exact three-file cardinality, strict UTF-8 JSON objects, no duplicate JSON keys or non-finite numbers, and exact caller-provided per-file digests.

The verifier job and the credentialed signer job independently repeat artifact metadata, bounded download, archive authentication, materialization, and file verification. Product code or product-provided scripts are never executed in the `attestations: write` job.

## Attestation and verification

The signer uses the immutable `actions/attest` v4.1.0 commit `59d89421af93a897026c735860bf21b6eb4f7b26` to attest the exact result subject digest with the trusted predicate. The workflow then verifies the result online against the caller repository, central signer repository/workflow, exact source digest, and predicate type.

For offline verification it retains the Sigstore bundle, trusted root, predicate, verifier manifest, and SHA-256 inventory. The retained README contains the exact online and offline `gh attestation verify` commands.

A valid bundle therefore answers “these are the authenticated evidence bytes for this exact CWL source/run.” It does **not** answer “p95 passed.” A product may issue a positive commercial performance receipt only after its own acceptance logic validates the authenticated evidence under its domain policy.

## Rejected alternatives

- **Caller-supplied result digest as trust root.** Rejected because a caller that can replace the result can also recompute the digest.
- **`github.workflow_sha` as reusable-workflow source identity.** Rejected for cross-repository callers because the reusable workflow inherits caller context. OIDC `job_workflow_ref`/`job_workflow_sha` is the prerequisite repair owned by #2164/#1228.
- **`actions/download-artifact` extraction before bounded validation.** Rejected because the archive would be expanded before the trusted verifier can enforce uncompressed limits. The current path authenticates and bounds the ZIP first, then uses the central materializer.
- **Central latency `PASS`.** Rejected because the organization signer owns evidence authenticity, not product workload semantics or acceptance thresholds.

## Verification gates

The quality workflow compiles the materializer, verifier, and tests on Python 3.10 and runs exact-head tests on the current quality Python. Both production scripts must retain 100% statement/branch coverage and 100% docstring coverage. Security/SAST/CodeQL remain separate hosted gates; non-terminal or central-control-plane failures are not converted into local GREEN evidence.

This contract remains mutable until its prerequisite stack is merged through protected review and a consumer canary verifies the immutable central workflow. Orgmetra must remain fail closed until then.

## References

GitHub. (2026). *REST API endpoints for GitHub Actions artifacts*. GitHub Docs. https://docs.github.com/en/rest/actions/artifacts

GitHub. (2026). *Using artifact attestations and reusable workflows to achieve SLSA v1 Build Level 3*. GitHub Docs. https://docs.github.com/en/actions/how-tos/secure-your-work/use-artifact-attestations/increase-security-rating

GitHub. (2026). *Verifying attestations offline*. GitHub Docs. https://docs.github.com/en/actions/how-tos/secure-your-work/use-artifact-attestations/verify-attestations-offline

GitHub. (2026). *Reusing workflow configurations*. GitHub Docs. https://docs.github.com/en/actions/how-tos/reuse-automations/reuse-workflows

GitHub. (2026). `actions/attest` v4.1.0, commit `59d89421af93a897026c735860bf21b6eb4f7b26`.

GitHub. (2026). `actions/upload-artifact` v7 documentation. The uploaded artifact digest is SHA-256 and the displayed artifact size refers to the ZIP representation. https://github.com/actions/upload-artifact
