# Noema observed-defect adversarial probe taxonomy

## Purpose

Noema formal review already required exact changed-line evidence and concrete adversarial probes before a verdict could be accepted. Live independent-review evidence showed that probe count alone is not enough: two generic attacks can satisfy a numeric diversity rule while omitting known high-value failure shapes such as mutable-alias escapes, validation/use races, execution-identity confusion, or weak test oracles.

This increment binds every formal adversarial probe to an executable defect class derived from independently observed repository findings. It does not claim parity or superiority over any proprietary reviewer; the corpus is an empirical regression set for this control plane.

## Observed defect classes

The central gate recognizes the following closed taxonomy:

- `mutable_alias`: caller-owned mutable references or shallow-readonly values can mutate admitted state after validation.
- `time_of_check_time_of_use`: getters, proxies, files, refs, or other evidence can change between validation and later consumption.
- `execution_identity`: a lifecycle or authorization signal can be replayed across execution, tenant, request, workflow, or head identities.
- `coercion_boundary`: implicit conversion can turn untrusted non-canonical values into enum keys, identifiers, digests, or authorization inputs.
- `test_oracle`: assertions can be substring-based, vacuous, tautological, or otherwise incapable of distinguishing the intended failure.
- `cross_contract`: code, tests, PRD, ADR, architecture, changelog, schema, or release-state claims contradict one another.
- `authority_boundary`: a component invents policy or authorization authority that belongs to a host, caller, tenant, or separate bounded context.
- `dependency_context`: omitted causal dependencies or unchanged delegated invariants can make a finding or clean verdict unsound.
- `state_machine_race`: cancellation, retry, publication, concurrency, stale-event, or transition ordering can produce an invalid state.

For material source or test changes, the existing two-probe minimum now also requires two distinct taxonomy classes. This prevents duplicated attacks of one shape from satisfying the review-diversity contract.

## Evidence and provenance

The initial corpus was grounded in independently observed findings on `ContextualWisdomLab/noema#528`: mutable checkpoint aliases, changing-getter/Proxy TOCTOU, cross-execution lifecycle identity, a substring test oracle that matched `released` inside `unreleased`, and cross-document contract contradictions. These are defect-shape examples, not evidence that Noema itself missed the identical historical review or that the resulting system is equivalent to the external reviewers.

The review prompt instructs the model to attack the closed taxonomy explicitly. The deterministic validator rejects non-string, missing, or unknown `probe_kind` values and requires an exact class-specific `class_evidence` witness schema before a label can count toward diversity. For example, mutable-alias evidence must identify the alias origin, mutation attempt, and post-validation observation; TOCTOU evidence must identify the checked value, intervening change, and later use. Published review evidence includes each validated probe class so operators can audit what was actually attacked rather than infer coverage from generic prose. The prompt no longer claims CodeGraph context is supplied: no trusted Noema workflow currently wires that input, so only actual changed-file and review-thread context is advertised.

## Verification contract

The focused regression suite must prove at least the following:

1. a missing probe class fails closed;
2. unknown, list-valued, or object-valued classes fail closed as review-validation errors rather than crashing;
3. arbitrary distinct labels without the exact class-specific witness schema fail closed;
4. two material-change probes using the same validated class fail the diversity requirement;
5. two valid class-bound observed probes can satisfy the formal verdict contract; and
6. an exercised `call_llm` request contains every supported class and its witness-field schema while making no unwired CodeGraph claim.

The initial hosted RED run was `33499442683`. The hosted GREEN implementation run was `33500648307`; it passed 118 focused Noema tests, the two exact-base free-pool fixture regressions exposed during full-suite verification, and the complete repository suite (`2278 passed, 1 skipped, 21 subtests passed`). That run proved the implementation before this permanent doctoring/quality-gate follow-up; the pull request's exact current head must regenerate its own required evidence. The one-shot workflow and transform scripts removed themselves before the implementation branch was published.

## Related exact-base correction

The full-suite verification also exposed two stale test inputs left by the immediately preceding `orchestrator/free` credential-source repair: generic account-cap and limit tests still used OpenAI as if it were an eligible free-pool source. Production policy correctly excludes `OPENAI_API_KEY` from `orchestrator/free` while retaining global discovery. Those generic fixtures now use OpenRouter, an authorized free-pool source. No production routing policy changed in this increment.

## Rollback

Rollback the production validator, prompt, new regression suite, migrated test fixtures, quality workflow, and the two stale generic free-pool fixture corrections together. Do not retain tests that require `probe_kind` while reverting production parsing, and do not restore OpenAI as a generic `orchestrator/free` test input unless the free-pool source contract itself is intentionally changed in a separately reviewed policy decision.

## References

GitHub. (2026). *About pull request reviews*. GitHub Docs. https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/reviewing-changes-in-pull-requests/about-pull-request-reviews

National Institute of Standards and Technology. (2022). *Secure Software Development Framework (SSDF) Version 1.1: Recommendations for mitigating the risk of software vulnerabilities* (NIST SP 800-218). https://doi.org/10.6028/NIST.SP.800-218

OWASP Foundation. (2021). *OWASP Code Review Guide, version 2.0*. https://owasp.org/www-project-code-review-guide/
