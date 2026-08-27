# Learning Interoperability Contracts hourly review-repair caller

## Status

Proposed on 2026-08-27 as the product-specific heartbeat for
`ContextualWisdomLab/learning-interoperability-contracts`. The target repository
remains the **rights-safe contract authority** for shared learning schemas,
profiles, generated clients, and conformance fixtures. Central `.github` owns
only reusable queue, credential, dispatch, review, and merge-control contracts.

## Buyer and ecosystem problem

The learning-contract repository was bootstrapped with `develop` as its release
base, while bounded follow-up contracts may be stacked on an unmerged feature
head. A scheduler limited to `develop` or `main` therefore misses the very PRs
that define the next CEFR, xAPI, QTI, accessibility, credential, or assessment
contract. Local checks can succeed while OpenCode, Strix, Noema, security, or
independent semantic review never reaches a stacked head.

The product must remain one versioned interoperability authority rather than a
collection of copied schemas across Learning Management Platform, Learning
Content Studio, Learning Record Store, Psychometrics Commons, fast-mlsirm,
TEPP, contextual-orchestrator, and Semantic Data Portal. An idle stacked PR can
block every consumer, but queue latency is not permission to bypass scientific,
rights, security, or branch-protection gates.

## Decision

The caller runs at minute 18 of every hour. Protected central `main` had no
existing `cron: "18 * * * *"` product heartbeat at the design head. It invokes
the sealed central `pr-review-fix-scheduler.yml` across **all PR bases** so both
the bootstrap root and its stacked children are visible.

Each heartbeat scans at most 50 open pull requests and dispatches at most one
writer. The **two-hour same-head retry floor** prevents a later heartbeat from
duplicating a legitimate OpenCode, Strix, Noema, standards, rights, security, or
cross-repository conformance investigation. Non-cancelling concurrency preserves
root-cause analysis already in progress.

A writer must establish the first causal boundary, verify the exact current head
and base, distinguish source-contract defects from consumer defects, compare
bounded remediation candidates, define RED-to-GREEN evidence, and change only
the owning repository. Review or check waiting does not prevent safe work on a
different eligible head.

## Standards, measurement, and rights boundary

The central Agent must not turn a standards reference into a certification
claim. In particular:

- xAPI 2.0 / ISO/IEC/IEEE 39274-1-1 remains the canonical learning-record
  contract while cmi5/xAPI 1.0.3 compatibility stays explicit and versioned;
- QTI, LTI, CASE, Open Badges, CLR, accessibility, and CEFR adoption remain
  separate from executable conformance or external certification;
- the Council of Europe does not verify a provider's CEFR linking claim;
- **official CEFR descriptor prose**, translations, language-specific Reference
  Level Description content, manuals, tasks, responses, audio, provider output,
  and PII must not be copied into a public interoperability fixture unless a
  reviewed rights record explicitly permits that use;
- CEFR alignment, empirical linking, and governed certification decisions remain
  distinct claim states;
- numerical psychometric work remains in fast-mlsirm's Rust-owned production
  layer and assessment-result authority remains in Psychometrics Commons;
- LLM observations remain fallible, evidence-bound rater observations and never
  become final proficiency truth in the contract repository.

An automated repair may strengthen schema, fixture, generated-client,
traceability, or conformance evidence. It may not invent a standard revision,
relax a closed schema to make a fixture pass, average ordinal proficiency levels,
remove uncertainty or non-measurement states, copy protected text, or move
runtime application state into the contract repository.

## Credential and approval boundary

The workflow-wide token remains read-only. The reusable caller job grants only
`contents: read` and `id-token: write`. The latter permits the established
central OpenCode GitHub App exchange when mapped `PR_REVIEW_MERGE_TOKEN` and
`OPENCODE_APPROVE_TOKEN` credentials are unavailable; it does not grant the
caller repository write, issue, pull-request, action, or status mutation.

The caller never uses `secrets: inherit` and does not receive
`NVIDIA_NIM_API_KEY`; model credentials stay sealed inside the reusable central
execution path. `COPILOT_GITHUB_TOKEN` is forbidden. Existing reviewer and
model-pool contracts are not changed by this caller.

Before protected merge, operators must verify that
`OPENCODE_REPOSITORY_DISPATCH_TARGETS` includes the exact
`ContextualWisdomLab/learning-interoperability-contracts` repository. A missing
allowlist entry fails closed rather than silently degrading the heartbeat into a
no-op.

A repair does not authorize approval or merge. The exact unchanged head still
requires terminal required checks, zero valid unresolved findings, qualifying
**independent non-author approval**, and ordinary branch-protection acceptance.
Agents must not self-approve, synthesize status evidence, weaken a ruleset,
force-cancel legitimate analysis, merge a stacked child into its feature base,
or treat a predecessor review as current-head evidence.

## Standalone and ecosystem operation

The contract repository remains independently understandable and publishable.
Consumers integrate through released schemas, generated SDKs, versioned
profiles, and conformance fixtures. The hourly caller may repair contract-owned
artifacts and consumer-contract evidence, but it may not write a sibling product,
read another product's database, or copy sibling implementation internals.

When a root PR merges, a stacked child must be deliberately retargeted or
restacked onto the protected release base. Every changed head receives fresh
required checks and semantic review. A green child check on a feature base is
useful evidence, not protected-release authorization.

## Verification and rollback

The caller, this doctoring record, and their contract test are tracked by the
permanent hourly review-repair quality workflow. Verification requires:

- exact schedule, all-base scan, bounded dispatch, retry, and non-cancellation
  assertions;
- workflow-wide read-only and job-scoped OIDC assertions;
- explicit credential mapping and forbidden-secret assertions;
- doctoring/quality path tracking;
- Python compile checks, complete owned coverage/docstrings, YAML parse, and
  `git diff --check`;
- exact-current-head protected GitHub checks and independent review.

Rollback removes the caller, focused test, doctoring record, and quality-workflow
tracking together. It must not leave a timer pointing at a renamed, mutable, or
unverified reusable workflow.

## APA 7th references

American Educational Research Association, American Psychological Association,
& National Council on Measurement in Education. (2014). *Standards for
educational and psychological testing*. American Educational Research
Association.

Council of Europe. (2020). *Common European Framework of Reference for
Languages: Learning, teaching, assessment—Companion volume*. Council of Europe
Publishing.

GitHub. (2026). *Security hardening for GitHub Actions*. GitHub Docs.
https://docs.github.com/en/actions/security-for-github-actions/security-guides/security-hardening-for-github-actions

International Organization for Standardization, International Electrotechnical
Commission, & Institute of Electrical and Electronics Engineers. (2025).
*Learning technology—JavaScript Object Notation data model format and RESTful
web service for learner experience data tracking and access—Part 1-1: xAPI using
JSON serialization and RESTful data transport (ISO/IEC/IEEE 39274-1-1:2025)*.
International Organization for Standardization.
