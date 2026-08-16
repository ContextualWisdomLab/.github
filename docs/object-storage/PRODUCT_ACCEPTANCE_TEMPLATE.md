# Object-storage product acceptance template

Use this checklist in the product repository that owns the adapter. Central
`.github` does not store customer objects. The current consumer is
[ContextualWisdomLab/naruon#1364](https://github.com/ContextualWisdomLab/naruon/pull/1364).

## Before you claim S3 compatibility

1. Commit a contract JSON that passes
   `python3 scripts/ci/validate_object_storage_contract.py --path <your-contract.json>`.
2. Keep provider selection tenant- and purpose-bound. Do not share one
   credential or bucket across tenants or unrelated jobs.
3. Persist provider and object metadata in 3NF with multiword `snake_case`
   names. Do not store credentials in events, logs, SBOMs, or model context.

## Failure-injection lane

A product may call itself S3-compatible only after a real object-store lane
(LocalStack or the purchased endpoint) proves write/read/delete behavior
against the current head, including:

| Case | Required next action |
|---|---|
| write timeout | Leave the previous durable object in place and record a purpose-bound audit event |
| read timeout | Fail closed; do not treat a truncated body as valid evidence |
| delete timeout | Retry the same deterministic key; do not enumerate the bucket |
| partial or aborted upload | Do not publish a `available` object; compensate without deleting older customer data |
| digest or content-length mismatch | Reject the read; keep the prior object |
| DNS TTL flip / rebinding | Pin the first resolved address for the request; do not look the name up again mid-transfer |

## Rollback and retention

A partial migration or backfill must not delete customer data. `consumed`
does not delete unless the product explicitly configures zero retention.
Legal hold and archive stay distinct from the reprocessing window.

## Telemetry

Emit OpenTelemetry or audit evidence without `bucket`, `object_key`,
`credential`, or `raw_pii` labels. Operational PII that the product must
process stays in the product data plane; do not blanket-mask it.

## Close the issue only with current-head proof

Point the product PR at this template, the central contract SHA, and the
exact-head integration run. Prose without that run does not close
ContextualWisdomLab/.github#1019.
