# OpenCode review false-positive and false-negative resistance — 2026-09-02

## Finding

The protected central OpenCode prompts had an internal authority contradiction. Their prime directive required source-backed material defects and prohibited style-only blocking findings, but later text made every new or renamed identifier a blocker unless it contained two or more meaningful words. The same section treated an exposed sequential identifier as automatic proof of an IDOR/enumeration defect and instructed the reviewer to assume exposure when that fact was unclear.

Those rules can generate false positives without tracing a consumer, authorization path, serializer, database, generated-code boundary, compatibility contract, or observable security impact. They also turn English lexical shape into review authority, which conflicts with the control plane's evidence-first and hallucination-resistance goals.

A second, opposite failure appeared during live peer review of the repair: after the blanket lexical rule was removed, the prompt said short or single-word names were acceptable without preserving the repository-specific contract for **new database objects**. `docs/product-goal-directive.md` §5 reconciles that rule against `docs/CWL-MASTER-CONTEXT.md` §7: new DB object names require 2+ word `snake_case`, while existing CamelCase/PascalCase DB objects are grandfathered. Devin correctly demonstrated that this cross-document contract could be lost by a locally reasonable prompt rewrite.

A third live finding arrived on the final #1654 head immediately before/after that PR was merged: the executable runtime prompt told an uncertain identifier review to return `NEEDS_INFO` or a non-blocking note, while `opencode-review-control-v1` and its normalizer/approval gate expose only `APPROVE` and `REQUEST_CHANGES`; moreover `REQUEST_CHANGES` requires a confirmed adversarial probe and source-backed finding. That is a state-machine/API contradiction, not a wording preference: the model can follow the review policy exactly and still emit a result the publication gate cannot represent.

A fourth peer review of #1655 exposed the remaining state-machine hole after the first schema repair. Leaving an unproven candidate uncounted is correct, but if the review as a whole lacks enough positive evidence for `APPROVE` and also lacks a confirmed source-backed defect for `REQUEST_CHANGES`, the two-result control schema still has no truthful verdict. Forcing either enum would fabricate evidence or approval.

## Repair

`ci-review-prompt.md`, `code-reviewer-prompt.md`, and the executable `scripts/ci/opencode_review_prompt_template.md` use general naming and identifier shape only as adversarial seeds. A reviewer must attempt to falsify a heuristic seed before blocking. Outside the explicit new-DB naming contract, naming becomes blocking only when the exact changed identifier has a source-backed consequence such as a real reserved-word collision, ambiguous serialization/generated code, public-contract incompatibility, portability break, or security/authority confusion.

The three prompt surfaces explicitly preserve the new-DB exception: new table, column, primary-key, foreign-key, index, and constraint names require at least two words in `snake_case`; existing CamelCase/PascalCase DB objects remain grandfathered and must not be force-renamed.

Sequential/exposed identifiers remain a security review signal, but no longer imply IDOR by themselves. The reviewer must trace the actual authorization and lookup path and block only when evidence shows unauthorized access, cross-tenant discovery, sensitive existence disclosure, or violation of an explicit opaque-identifier contract. Properly authorized or intentionally public sequential identifiers can be acceptable.

For the **gated** CI/runtime surfaces, the two-result `opencode-review-control-v1` schema remains unchanged. Confirmed current-head defects use `REQUEST_CHANGES`; sufficiently evidenced safe reviews use `APPROVE`; bounded uncertainty inside an otherwise valid approval remains in `adversarial_validation.residual_risk`. When neither schema verdict can be truthfully supported, the model emits the ordinary current-head sentinel plus an `opencode-review-needs-info` marker and deliberately omits the control block. The existing approval gate therefore returns `NO_CONCLUSION` and the required workflow stays non-passing. This is a fail-closed transport state, not a third control result, and it does not invent a confirmed defect. The standalone `code-reviewer-prompt.md` may still use its human-facing `NEEDS_INFO` verdict because that separate contract explicitly supports it.

## Durable false-negative corpus

The review contract makes recurring externally demonstrated failure classes explicit adversarial targets rather than waiting for peer reviewers to rediscover them. Reviewers must actively probe mutable aliases/post-validation mutation, changing getter/Proxy or other TOCTOU behavior, execution/tenant/request identity confusion, stale head/event evidence, substring-only/existence-only/vacuous test oracles, cross-file or cross-document contract contradictions, internal/external authority overreach, security/reliability state-machine races, and missing causal dependency context.

Each candidate must stay tied to an exact changed source line and causal path, receive a disconfirming probe, and be classified as a confirmed defect, falsified/false positive, or left uncounted when evidence is insufficient. An uncounted candidate is not a confirmed adversarial outcome. A single observation may not be relabelled as multiple defect classes, and taxonomy alone is never impact evidence.

## Regression

`tests/test_opencode_review_prompt_false_positive_resistance.py` covers all three prompt surfaces, including the live runtime template. It fails if the prompts restore the blanket lexical blocker, the assume-exposed IDOR rule, the unsupported incident anecdote, lose the evidence-driven authorization/consumer-path contract, erase the new-DB naming exception, or stop naming the durable false-negative probe classes above.

`tests/test_opencode_review_uncertainty_fail_closed.py` exercises the exact insufficient-evidence state found by peer review. Both gated prompt surfaces must name the `opencode-review-needs-info`/`NO_CONCLUSION` path and explicitly omit `opencode-review-control-v1`; the test then invokes `opencode_review_approve_gate.sh` with a valid current-head sentinel and needs-info marker but no control block and requires exit code 4 with `NO_CONCLUSION`. This proves the gate fails closed without widening the published result enum or synthesizing a finding.

## Review convergence and operating boundary

The external review finding that the runtime template escaped the first regression was repaired before resolution. The later live finding that single-word DB names could bypass organization governance was independently traced to `docs/product-goal-directive.md` §5 / `docs/CWL-MASTER-CONTEXT.md` §7, converted into a regression, repaired on all three prompt surfaces, and only then resolved. A subsequent peer observation that the new false-negative-prefix test had no matching prompt paragraph became obsolete after the GREEN prompt commits and was resolved from exact-head source evidence.

The schema-representability finding was not left as a merged-PR comment. After #1654 landed on protected `main`, a fresh owner-side branch was cut from the exact merge commit, a RED regression was committed first, and the gated CI/runtime prompts were repaired. When protected `main` advanced again, #1655 was reconciled non-destructively with a two-parent commit built from the new protected-main tree before carrying only the five-file semantic delta forward. The later peer finding about the no-valid-verdict state produced a second RED regression and the explicit fail-closed transport state above rather than a fabricated blocker or a weakened approval contract.

This hardening does not claim benchmark superiority over CodeRabbit or Devin and does not copy proprietary wording. It converts observable peer-review misses into executable local contracts while preserving authorization review, tenant isolation, exact changed-line evidence, adversarial validation, CodeGraph evidence, security checks, and the read-only reviewer sandbox.
