# OpenCode review false-positive resistance — 2026-09-02

## Finding

The protected central OpenCode prompts had an internal authority contradiction. Their prime directive required source-backed material defects and prohibited style-only blocking findings, but later text made every new or renamed identifier a blocker unless it contained two or more meaningful words. The same section treated an exposed sequential identifier as automatic proof of an IDOR/enumeration defect and instructed the reviewer to assume exposure when that fact was unclear.

Those rules can generate false positives without tracing a consumer, authorization path, serializer, database, generated-code boundary, compatibility contract, or observable security impact. They also turn English lexical shape into review authority, which conflicts with the control plane's evidence-first and hallucination-resistance goals.

## Repair

Both `ci-review-prompt.md` and `code-reviewer-prompt.md` now use naming and identifier shape only as adversarial seeds. A reviewer must attempt to falsify a heuristic seed before blocking. Naming becomes blocking only when the exact changed identifier has a source-backed consequence such as a real reserved-word collision, ambiguous serialization/generated code, public-contract incompatibility, portability break, or security/authority confusion.

Sequential/exposed identifiers remain a security review signal, but no longer imply IDOR by themselves. The reviewer must trace the actual authorization and lookup path and block only when evidence shows unauthorized access, cross-tenant discovery, sensitive existence disclosure, or violation of an explicit opaque-identifier contract. Properly authorized or intentionally public sequential identifiers can be acceptable. When the exposure or authorization consequence is genuinely unavailable, the prompt requires focused `NEEDS_INFO` or a non-blocking risk note rather than fabricated exploitability.

## Regression

`tests/test_opencode_review_prompt_false_positive_resistance.py` fails if either OpenCode review prompt restores the blanket two-word rule, the "assume exposed" rule, the unsupported incident anecdote, or loses the evidence-driven authorization/consumer-path contract.

This is a false-positive-resistance improvement only. It does not weaken authorization review, tenant isolation, exact changed-line evidence, adversarial validation, CodeGraph evidence, security checks, or the read-only reviewer sandbox.
