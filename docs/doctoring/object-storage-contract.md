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
2. Require HTTPS, exact-host allowlists, no wildcards, no automatic
   redirects, and DNS pinning for the request lifetime (CWE-918; Jackson
   et al., 2009). DNS-rebinding helper suffixes, RFC 6761 `.test` /
   `.invalid` names, and hosts that embed a dotted IPv4 address or a 32-bit
   numeric alias (for example `169.254.169.254.attacker.example` or
   `169-254-169-254.attacker.example`) are never allowlist members.
3. Require explicit private-network trust. Implicit RFC1918, metadata-service,
   multicast `.local` (Cheshire & Krochmal, 2013b), Kubernetes `.svc`
   names (The Kubernetes Authors, n.d.), or special-use internal suffixes
   (Cheshire & Krochmal, 2013a) are not authorized unless the exact host is
   named after an explicit trust decision. Multicast `.local` names are
   never unicast endpoints.
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
10. Require tenant- and purpose-bound provider selection so one credential or
    bucket cannot serve unrelated tenants or jobs.
11. Ship an executable validator and a product acceptance template. Prose
    alone does not close ContextualWisdomLab/.github#1019.

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
unique rejection. `tests/test_object_storage_contract_hardening.py` proves
nested schema objects stay closed, NaN/Infinity are rejected, exact-host
allowlists exclude localhost, metadata, cluster-local names, IPv4 and IPv6
literals, decimal or hexadecimal IP aliases, Unicode, case aliases, and
multicast `.local` names, a denied private-network policy rejects
single-label, Kubernetes `.svc`, and special-use internal hosts, custom
endpoints reject ports above 65535, schema value constraints match the
validator including the consumed/zero-retention coupling, tenant-purpose
binding and DNS pinning are mandatory, DNS-rebinding helper suffixes and
embedded or hyphenated IPv4 or 32-bit numeric aliases stay off the allowlist, and
malformed observability labels raise policy errors
instead of TypeError. Local quality remains 100% statement/branch coverage
and 100% docstrings.

## Rollback

Revert the validator, schema, example, policy, and this record together. Do
not keep a schema that the executable check no longer enforces.

## References (APA 7th)

Jackson, C., Barth, A., Bortz, A., Shao, W., & Boneh, D. (2009). Protecting
browsers from DNS rebinding attacks. *ACM Transactions on the Web, 3*(1),
Article 2, 1–26. https://doi.org/10.1145/1462148.1462150

The Kubernetes Authors. (n.d.). *DNS for Services and Pods*. Kubernetes
Documentation.
https://kubernetes.io/docs/concepts/services-networking/dns-pod-service/

Cheshire, S., & Krochmal, M. (2013a). *Special-use domain names* (RFC 6761).
Internet Engineering Task Force. https://www.rfc-editor.org/rfc/rfc6761

Cheshire, S., & Krochmal, M. (2013b). *Multicast DNS* (RFC 6762). Internet
Engineering Task Force. https://www.rfc-editor.org/rfc/rfc6762

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
