# OpenCode review false-positive and false-negative resistance — 2026-09-02

## Finding

The protected central OpenCode prompts had an internal authority contradiction. Their prime directive required source-backed material defects and prohibited style-only blocking findings, but later text made every new or renamed identifier a blocker unless it contained two or more meaningful words. The same section treated an exposed sequential identifier as automatic proof of an IDOR/enumeration defect and instructed the reviewer to assume exposure when that fact was unclear.

Those rules can generate false positives without tracing a consumer, authorization path, serializer, database, generated-code boundary, compatibility contract, or observable security impact. They also turn English lexical shape into review authority, which conflicts with the control plane's evidence-first and hallucination-resistance goals.

A second, opposite failure appeared during live peer review of the repair: after the blanket lexical rule was removed, the prompt said short or single-word names were acceptable without preserving the repository-specific contract for **new database objects**. `docs/product-goal-directive.md` §5 reconciles that rule against `docs/CWL-MASTER-CONTEXT.md` §7: new DB object names require 2+ word `snake_case`, while existing CamelCase/PascalCase DB objects are grandfathered. Devin correctly demonstrated that this cross-document contract could be lost by a locally reasonable prompt rewrite.

## Repair

`ci-review-prompt.md`, `code-reviewer-prompt.md`, and the executable `scripts/ci/opencode_review_prompt_template.md` now use general naming and identifier shape only as adversarial seeds. A reviewer must attempt to falsify a heuristic seed before blocking. Outside the explicit new-DB naming contract, naming becomes blocking only when the exact changed identifier has a source-backed consequence such as a real reserved-word collision, ambiguous serialization/generated code, public-contract incompatibility, portability break, or security/authority confusion.

The three prompt surfaces explicitly preserve the new-DB exception: new table, column, primary-key, foreign-key, index, and constraint names require at least two words in `snake_case`; existing CamelCase/PascalCase DB objects remain grandfathered and must not be force-renamed.

Sequential/exposed identifiers remain a security review signal, but no longer imply IDOR by themselves. The reviewer must trace the actual authorization and lookup path and block only when evidence shows unauthorized access, cross-tenant discovery, sensitive existence disclosure, or violation of an explicit opaque-identifier contract. Properly authorized or intentionally public sequential identifiers can be acceptable. When the exposure or authorization consequence is genuinely unavailable, the prompt requires focused `NEEDS_INFO` or a non-blocking risk note rather than fabricated exploitability.

## Durable false-negative corpus

The review contract now makes recurring externally demonstrated failure classes explicit adversarial targets rather than waiting for peer reviewers to rediscover them. Reviewers must actively probe mutable aliases/post-validation mutation, changing getter/Proxy or other TOCTOU behavior, execution/tenant/request identity confusion, stale head/event evidence, substring-only/existence-only/vacuous test oracles, cross-file or cross-document contract contradictions, internal/external authority overreach, security/reliability state-machine races, and missing causal dependency context.

Each candidate must stay tied to an exact changed source line and causal path, receive a disconfirming probe, and be classified as a confirmed defect, falsified/false positive, or `NEEDS_INFO`. A single observation may not be relabelled as multiple defect classes, and taxonomy alone is never impact evidence.

## Regression

`tests/test_opencode_review_prompt_false_positive_resistance.py` now covers all three prompt surfaces, including the live runtime template. It fails if the prompts restore the blanket lexical blocker, the assume-exposed IDOR rule, the unsupported incident anecdote, lose the evidence-driven authorization/consumer-path contract, erase the new-DB naming exception, or stop naming the durable false-negative probe classes above.

The regression is paragraph-scoped so scattered substrings cannot satisfy the contract. The runtime template also retains current-head and language-evidence authority, and the CI prompt retains its established adversarial probe-count thresholds.

## Review convergence and operating boundary

The external review finding that the runtime template escaped the first regression was repaired before resolution. The later live finding that single-word DB names could bypass organization governance was independently traced to `docs/product-goal-directive.md` §5 / `docs/CWL-MASTER-CONTEXT.md` §7, converted into a regression, repaired on all three prompt surfaces, and only then resolved. A subsequent peer observation that the new false-negative-prefix test had no matching prompt paragraph became obsolete after the GREEN prompt commits and was resolved from exact-head source evidence.

This hardening does not claim benchmark superiority over CodeRabbit or Devin and does not copy proprietary wording. It converts observable peer-review misses into executable local contracts while preserving authorization review, tenant isolation, exact changed-line evidence, adversarial validation, CodeGraph evidence, security checks, and the read-only reviewer sandbox.
