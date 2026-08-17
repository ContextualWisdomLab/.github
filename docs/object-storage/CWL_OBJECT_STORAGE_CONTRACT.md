# CWL object-storage contract

This repository owns the reusable `object_storage` policy and the executable
check `scripts/ci/validate_object_storage_contract.py`. Product repositories
keep their own adapters, databases, and evidence objects. Naruon
[ContextualWisdomLab/naruon#1364](https://github.com/ContextualWisdomLab/naruon/pull/1364)
is the current concrete consumer and remains the owner of its document-storage
implementation.

AWS-managed S3 and S3-compatible HTTPS endpoints are one provider-neutral
capability. They are not an AWS-only product assumption.

## Closed controls

A contract JSON document is valid only when every control below is true.

| Control | Required value |
|---|---|
| Transport | `https` only |
| Hosts | exact-host allowlist; no wildcards; no automatic redirects; no multicast `.local`, metadata, RFC 6761 `.test`/`.invalid`, DNS-rebinding helper names, or embedded IPv4 / 32-bit numeric aliases |
| DNS pinning | resolve once and pin the address for the request lifetime; a later TTL flip must not retarget the socket |
| Private networks | `explicit_allowlist` or `denied`; never implicit RFC1918, RFC 6761/6762, Kubernetes `.svc`, or `.internal` access |
| Credentials | scoped secret registry or workload identity; never broadcast, browser-exposed, or ambient process-wide |
| Permissions | least privilege; public ACLs and public buckets prohibited |
| Encryption | server-side encryption `required` |
| Integrity | content length plus SHA-256 or stronger; fail-closed read verification |
| Lifecycle | `pending`, `available`, `consumed`, `archived`, and `held` are distinct; `consumed` does not delete unless zero retention is explicit |
| Rollback | a partial migration must not delete customer data |
| Names | persisted metadata uses multiword `snake_case` |
| Tenant binding | provider selection is tenant- and purpose-bound |
| Telemetry | bucket names, object keys, credentials, and raw PII are forbidden high-cardinality labels |
| Assurance | CSAP and SOC 2 are design constraints, not certifications |

Operational PII stays usable through the owning product. Forbidding
high-cardinality labels is not a blanket PII mask.

## Endpoint classes

1. **AWS-managed S3 HTTPS endpoints** — `provider_class` is `aws_s3` and every
   host is an exact Amazon S3 regional or dual-stack name.
2. **Public S3-compatible HTTPS endpoints** — `provider_class` is
   `s3_compatible` and every host is an exact public DNS name.
3. **Authorized private-network endpoints** — `private_network_trust` is
   `explicit_allowlist` and each private host is named. Implicit RFC1918,
   link-local, metadata-service, multicast `.local`, or special-use
   `.internal` / `.corp` / `.lan` / `.svc` access is rejected unless that exact
   host is named after an explicit trust decision. Multicast `.local` names,
   DNS-rebinding helpers such as `.nip.io`, and hosts that embed a dotted IPv4
   address or 32-bit numeric alias (for example `169.254.169.254.attacker.example`)
   are never valid unicast endpoints.

Workload-identity and instance-metadata access require their own SSRF review.
This contract does not grant that access.

## Product next actions

On success the consumer persists or reads the object under its own schema and
records a purpose-bound audit event without bucket, key, credential, or raw PII
labels. On rejection, timeout, duplicate, or partial upload the consumer leaves
the previous durable object in place. Rollback never deletes customer data
because a backfill step only partly succeeded. Product repositories then run
the write/read/delete failure-injection lane in
`docs/object-storage/PRODUCT_ACCEPTANCE_TEMPLATE.md`.

## Verification

```bash
python3 scripts/ci/validate_object_storage_contract.py \
  --path schemas/examples/cwl-object-storage-v1.example.json
```

The checked-in example is the naruon-shaped fixture. A product repository may
commit its own contract file and run the same command in its quality job. The
issue is not closed by prose alone: the executable check is the acceptance
evidence.

## Schema

`schemas/cwl-object-storage-v1.schema.json` lists the closed top-level keys.
The Python validator is authoritative when a JSON Schema library is not
installed.
