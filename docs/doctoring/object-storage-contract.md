# Object-storage contract: evidence and design record

검토 기준일: **2026-08-16**

## Incident / buyer-visible gap

Sibling products persist customer or evidence objects in AWS S3 or
S3-compatible stores. Without a central executable contract, each repository
can invent endpoint, credential, encryption, integrity, retention, and
rollback rules. That drift is a procurement and data-loss risk for buyers who
must keep documents, even when Naruon already implements a scoped adapter in
ContextualWisdomLab/naruon#1364.

This record does not implement Naruon storage. It records the organization
policy and the fail-closed check that leaf repositories can cite.

## Decision

1. Treat AWS S3 and S3-compatible HTTPS stores as one `object_storage`
   capability.
2. Require HTTPS, exact-host allowlists, no wildcards, and no automatic
   redirects (CWE-918).
3. Require explicit private-network trust. Implicit RFC1918 or metadata-service
   access is not authorized by this contract.
4. Require least-privilege object permissions and prohibit public ACLs, public
   buckets, and browser-exposed long-lived credentials (CWE-798; CWE-200).
5. Require server-side encryption and fail-closed content-length plus SHA-256
   or stronger read verification (Amazon Web Services, 2024a, 2024b).
6. Keep lifecycle states distinct. `consumed` does not imply immediate
   deletion unless the product explicitly configures zero retention. Legal hold
   and archive remain separate from transient reprocessing retention.
7. Refuse rollback that deletes customer data after a partial
   migration or backfill.
8. Forbid bucket names, object keys, credentials, and raw PII as unbounded
   telemetry labels. This is not a blanket operational PII mask.
9. Record CSAP and SOC 2 only as design constraints. The contract must not
   claim certification.
10. Ship an executable validator. Prose alone does not close
    ContextualWisdomLab/.github#1019.

## Trust boundary

- Central `.github` owns the schema, policy, doctoring record, and validator.
- Product repositories own adapters, buckets, keys, credentials, and evidence
  objects.
- NVIDIA NIM / OpenCode credentials are untouched.
- The validator never prints bucket names, object keys, or secrets from a
  failing document beyond the field that violated the closed policy.

## Verification contract

`tests/test_object_storage_contract.py` proves the checked-in example passes,
the schema keys match production constants, and each fail-closed control has a
unique rejection. Local quality remains 100% statement/branch coverage and
100% docstrings.

## Rollback

Revert the validator, schema, example, policy, and this record together. Do
not keep a schema that the executable check no longer enforces.

## References (APA 7th)

Amazon Web Services. (2024a). *Checking object integrity for data uploads in
Amazon S3*. Amazon Simple Storage Service User Guide.
https://docs.aws.amazon.com/AmazonS3/latest/userguide/checking-object-integrity-upload.html

Amazon Web Services. (2024b). *Using server-side encryption with AWS KMS keys
(SSE-KMS)*. Amazon Simple Storage Service User Guide.
https://docs.aws.amazon.com/AmazonS3/latest/userguide/UsingKMSEncryption.html

Amazon Web Services. (n.d.). *Authenticating requests (AWS Signature Version
4)*. Amazon Simple Storage Service API Reference.
https://docs.aws.amazon.com/AmazonS3/latest/API/sig-v4-authenticating-requests.html

MITRE. (n.d.-a). *CWE-200: Exposure of sensitive information to an
unauthorized actor*. CWE List.
https://cwe.mitre.org/data/definitions/200.html

MITRE. (n.d.-b). *CWE-798: Use of hard-coded credentials*. CWE List.
https://cwe.mitre.org/data/definitions/798.html

MITRE. (n.d.-c). *CWE-918: Server-side request forgery (SSRF)*. CWE List.
https://cwe.mitre.org/data/definitions/918.html
