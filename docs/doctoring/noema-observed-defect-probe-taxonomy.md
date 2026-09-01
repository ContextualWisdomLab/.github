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

The review prompt instructs the model to attack the closed taxonomy explicitly. The deterministic validator rejects non-string, missing, or unknown `probe_kind` values and requires an exact class-specific `class_evidence` witness schema before a label can count toward diversity. Each class-specific witness field must be an exact `{path, line, side}` reference equal to the probe's changed-side location; free-form boilerplate and borrowing another changed line fail closed. For example, mutable-alias evidence must supply the alias-origin, mutation-attempt, and post-validation-observation roles, while TOCTOU evidence must supply checked-value, intervening-change, and later-use roles. The source binding is deterministic; semantic interpretation remains auditable through the class-specific role names plus the probe's concrete hypothesis, attack/counterexample, outcome, and evidence. Published review evidence includes each validated probe class so operators can inspect what was actually attacked rather than infer coverage from generic prose.

The prompt no longer claims CodeGraph context is supplied: no trusted Noema workflow currently wires that input, so only actual changed-file and review-thread context is advertised. Protected-main deleted-file evidence remains intact: current `main` supplies immutable merge-base lookup and pre-deletion content for removed paths, and the reconciled branch preserves that stronger context boundary.

## Verification contract

The focused regression suite must prove at least the following:

1. a missing probe class fails closed;
2. unknown, list-valued, or object-valued classes fail closed as review-validation errors rather than crashing;
3. arbitrary distinct labels without the exact class-specific witness schema fail closed;
4. generic boilerplate class witnesses fail closed rather than authorizing diversity;
5. a class witness cannot borrow another changed line as its probe evidence;
6. two material-change probes using the same validated class fail the diversity requirement;
7. two valid source-bound class probes can satisfy the formal verdict contract;
8. an exercised `call_llm` request contains every supported class and its witness-field schema while making no unwired CodeGraph claim; and
9. every requirements file installed by the permanent observed-probe workflow is included in that workflow's `pull_request.paths`, so lockfile-only environment changes cannot bypass the focused contracts.

Historical TDD evidence remains predecessor evidence only: hosted RED run `33499442683` established the missing taxonomy contract, and hosted GREEN run `33500648307` passed the then-current focused and full suites. A later independent Devin review demonstrated that non-empty free-form `class_evidence` could still manufacture apparent diversity; the follow-up regression rejects generic prose and unrelated changed-line references, and the validator now requires exact structured changed-line references for every class-specific witness field.

At protected-main reconciliation on 2026-09-01, `main@6eb93bce8575ba734f5ce6cb9267d76f18f73680` became the exact merge base of the candidate branch. That reconciliation retained the probe taxonomy while inheriting the newer deleted-file merge-base context and the already-landed `orchestrator/free` fixture truth from protected main. Stale duplicate free-pool and branch-coverage deltas therefore disappeared from the effective PR diff. Temporary `source-fix-1589*` writer workflows are absent from the reconciled candidate. Only fresh evidence for the post-reconciliation exact head is eligible for merge.

## Rollback

Rollback the production taxonomy validator, prompt contract, observed-probe regression suites, focused quality workflow, doctoring, and product-gap traceability together. Do not retain tests that require `probe_kind` while reverting production parsing. Protected-main deleted-file context, routing policy, free-pool fixture truth, and unrelated control-plane repairs are not owned by this increment and must not be rolled back with it.

## References

GitHub. (2026). *About pull request reviews*. GitHub Docs. https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/reviewing-changes-in-pull-requests/about-pull-request-reviews

National Institute of Standards and Technology. (2022). *Secure Software Development Framework (SSDF) Version 1.1: Recommendations for mitigating the risk of software vulnerabilities* (NIST SP 800-218). https://doi.org/10.6028/NIST.SP.800-218

OWASP Foundation. (2021). *OWASP Code Review Guide, version 2.0*. https://owasp.org/www-project-code-review-guide/
