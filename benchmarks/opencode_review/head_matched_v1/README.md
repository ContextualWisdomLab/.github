# Head-matched OpenCode review corpus v1

This directory is the versioned landing area for real, exact-head code-review
quality evidence. It intentionally contains no fabricated expert annotations or
synthetic parity result.

## Required lifecycle

```text
trusted exact-head inventory
→ deterministic policy-complete sample
→ two independent blinded expert annotations
→ third-party blinded adjudication
→ immutable gold freeze
→ same-head OpenCode and CodeRabbit capture
→ scorer input assembly
→ frozen benchmark report
```

Gold must be frozen before either automated reviewer output is disclosed to the
experts or adjudicator. Lifecycle pilot data under `../pilot_baseline_v1.json`
remains operational telemetry and must not be copied into this expert-gold
answer key.

## Expected layout

```text
head_matched_v1/
├── README.md
├── inventory.json
├── sample.json
├── partition_manifest.json
└── cases/
    └── case_001/
        ├── context_manifest.json
        ├── expert_a.json
        ├── expert_b.json
        ├── adjudication.json
        ├── gold.json
        ├── opencode_review.json
        └── coderabbit_review.json
```

The repository may store large or access-restricted context bundles outside Git
when required. `context_manifest.json` must then retain immutable object
identities, content digests, access classification, and reproduction
instructions without embedding credentials.

## Tooling

Select an eligible sample:

```bash
python scripts/ci/opencode_review_sample.py \
  --input benchmarks/opencode_review/head_matched_v1/inventory.json \
  --output benchmarks/opencode_review/head_matched_v1/sample.json \
  --seed opencode-review-head-matched-v1
```

Freeze one adjudicated case:

```bash
python scripts/ci/opencode_review_adjudicate.py \
  --expert-a benchmarks/opencode_review/head_matched_v1/cases/case_001/expert_a.json \
  --expert-b benchmarks/opencode_review/head_matched_v1/cases/case_001/expert_b.json \
  --adjudication benchmarks/opencode_review/head_matched_v1/cases/case_001/adjudication.json \
  --output benchmarks/opencode_review/head_matched_v1/cases/case_001/gold.json
```

Both tools are offline, strict-JSON, deterministic utilities. They do not call
GitHub, execute repository code, inspect model credentials, or create human
judgments.

## Admission rules

- Same repository, pull request, base SHA, head SHA, diff digest, and context
  digest across every record.
- Complete repository context available to both experts.
- Same-head OpenCode and CodeRabbit review possible.
- Two distinct independent expert annotators and a distinct adjudicator.
- Required language, diff-size, risk, and defect-class strata represented.
- Every expert finding adjudicated exactly once.
- Every accepted gold finding carries path, positive line, class, severity,
  trigger, impact, root cause, fix direction, and regression target.
- No secrets, cookies, tokens, or unrelated personal data.
- No related-change family leakage across development, calibration, and held-out
  partitions.

## Current status

`EMPTY_PENDING_REAL_COLLECTION`

The absence of cases is not a passing parity result. OpenCode Review remains
`INSUFFICIENT_EVIDENCE` until a frozen corpus meets the configured minimum case
and gold-finding floors and the separately versioned statistical gate passes.
