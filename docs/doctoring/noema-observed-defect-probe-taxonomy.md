# Noema observed-defect adversarial probe taxonomy

## Purpose

Noema formal review already required exact changed-line evidence and concrete adversarial probes before a verdict could be accepted. Live independent-review evidence showed that probe count alone is not enough: two generic attacks can satisfy a numeric diversity rule while omitting known high-value failure shapes such as mutable-alias escapes, validation/use races, execution-identity confusion, or weak test oracles.

This increment binds every completed Noema review to executable evidence derived from independently observed repository findings. That includes GitHub `COMMENT` reviews: a non-blocking comment is presentation semantics, not a way to publish a completed review without changed-line analysis and adversarial probes. It does not claim parity or superiority over any proprietary reviewer; the corpus is an empirical regression set for this control plane.

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

For material source or test changes, the existing two-probe minimum now also requires two distinct taxonomy classes. This prevents duplicated attacks of one shape from satisfying the review-diversity contract. `COMMENT` is admitted against the same evidence contract as `APPROVE`: validation status must be `passed`, required probes must be present and distinct, and no confirmed adversarial defect may be hidden in a non-blocking comment. A confirmed defect belongs in `REQUEST_CHANGES`.

## Evidence and provenance

The initial corpus was grounded in independently observed findings on `ContextualWisdomLab/noema#528`: mutable checkpoint aliases, changing-getter/Proxy TOCTOU, cross-execution lifecycle identity, a substring test oracle that matched `released` inside `unreleased`, and cross-document contract contradictions. These are defect-shape examples, not evidence that Noema itself missed the identical historical review or that the resulting system is equivalent to the external reviewers.

The review prompt instructs the model to attack the closed taxonomy explicitly. The deterministic validator rejects non-string, missing, or unknown `probe_kind` values and requires an exact class-specific `class_evidence` witness schema before a label can count toward diversity. Each class-specific witness field must be an exact `{path, line, side}` reference equal to the probe's changed-side location; free-form boilerplate and borrowing another changed line fail closed. For example, mutable-alias evidence must supply the alias-origin, mutation-attempt, and post-validation-observation roles, while TOCTOU evidence must supply checked-value, intervening-change, and later-use roles. The source binding is deterministic; semantic interpretation remains auditable through the class-specific role names plus the probe's concrete hypothesis, attack/counterexample, outcome, and evidence. Published review evidence includes each validated probe class so operators can inspect what was actually attacked rather than infer coverage from generic prose.

The public `scripts.ci.noema_review_gate` entrypoint is now a deliberately small admission layer over the private implementation core. It installs the strict completed-verdict validator into the core before any model call or CLI execution, and normal imports resolve to the same patched module object so repository monkeypatch/test seams cannot accidentally exercise a weaker policy than production. This separation exists to make the completed-review admission policy independently reviewable; it is not a second reviewer implementation.

The trusted Noema path now materializes bounded CodeGraph evidence from an exact-head PR-source clone before model execution. The reviewer step already sources `load_contextual_orchestrator_token.sh` after selecting a repository-scoped reviewer credential; that sourced seam now detects Noema from its credential provenance, refreshes the live PR through the same selected `GH_TOKEN`, verifies the trigger head again, snapshots the current base SHA, and invokes the trusted CodeGraph helper. The helper executes only the lock-pinned central CodeGraph CLI, removes GitHub credentials before indexing/exploration, forbids target-owned test/build tooling in the helper contract, and writes a current-head marker under `runner.temp`. The Python core requires that packet and fails closed on missing, oversized, non-regular, or stale-head evidence. This avoids a second credential-bearing workflow step while preserving exact-head binding and the existing sidecar secret boundary.

CodeGraph changed-scope evidence follows GitHub pull-request semantics rather than a direct current-base-to-head tree diff. A branch can fall behind while protected `main` advances; direct base-to-head comparison would then mislabel upstream-only files as PR changes and pollute dependency context. The helper first resolves the actual merge base of the exact materialized base/head pair. Because the initial source fetch is intentionally shallow, it deepens both immutable histories only through bounded increments and fails closed if a common ancestor cannot be established. After deepening it re-verifies both exact refs, requires the merge base to be an ancestor of each side, scopes changed files from merge-base to head, and records the merge-base SHA in the evidence packet. This preserves stale-evidence resistance while preventing unrelated protected-main changes from entering the model's changed-file hypothesis.

## Verification contract

The focused regression suite must prove at least the following:

1. a missing probe class fails closed;
2. unknown, list-valued, or object-valued classes fail closed as review-validation errors rather than crashing;
3. arbitrary distinct labels without the exact class-specific witness schema fail closed;
4. generic boilerplate class witnesses fail closed rather than authorizing diversity;
5. a class witness cannot borrow another changed line as its probe evidence;
6. two material-change probes using the same validated class fail the diversity requirement;
7. two valid source-bound class probes can satisfy the formal verdict contract;
8. an exercised `call_llm` request contains every supported class and its witness-field schema while preserving the supplied bounded evidence;
9. a `COMMENT` without changed-line/probe evidence fails closed, while an evidence-bearing material comment requires two distinct observed classes and production `call_llm` is runtime-bound to that strict validator;
10. the CodeGraph helper is an executable/syntax-valid Bash program, treats target source as data only, and never executes target-owned tests/builds;
11. sourcing the production contextual-orchestrator token loader with Noema provenance refreshes the live PR, exports required CodeGraph context, and refuses a changed head before invoking the helper;
12. the gate accepts only a required packet bound to the exact reviewed head and rejects a predecessor packet or missing packet;
13. every code/test/requirements seam exercised by the permanent observed-probe workflow is included in that workflow's `pull_request.paths`, so lockfile-only or loader-only changes cannot bypass the focused contracts; and
14. an executable real-helper regression with a deliberately diverged base/head history excludes base-only paths while retaining PR-owned paths in the CodeGraph exploration scope.

Historical TDD evidence remains predecessor evidence only: hosted RED run `33499442683` established the missing taxonomy contract, and hosted GREEN run `33500648307` passed the then-current focused and full suites. A later independent Devin review demonstrated that non-empty free-form `class_evidence` could still manufacture apparent diversity; the follow-up regression rejects generic prose and unrelated changed-line references, and the validator now requires exact structured changed-line references for every class-specific witness field. Exact-head run `33513376931` then established a second RED: the branch had tests and a helper that claimed CodeGraph materialization but the production Noema execution path never invoked it. That failure is the regression anchor for the loader wiring and executable-helper repair; it is not eligible as GREEN evidence.

A subsequent current-head Devin review found that the helper's direct `refs/noema/base..refs/noema/head` changed-scope calculation did not match GitHub PR semantics for a behind branch. The regression-first commit `3e8617f84715ae2e7abe1e6bb1fabd51c3aabbe5` added an executable diverged-history case in which current-base comparison admits `base-only.txt`; the causal repair commit `634716f5ed62180d057434e521c09bfaaeb743d3` changes the helper to bounded merge-base resolution and merge-base-to-head scope. These commit identities are lineage evidence only; fresh checks and review on the final exact head remain authoritative.

At protected-main reconciliation on 2026-09-01, `main@6eb93bce8575ba734f5ce6cb9267d76f18f73680` became the exact merge base of the candidate branch. That reconciliation retained the probe taxonomy while inheriting the newer deleted-file merge-base context and the already-landed `orchestrator/free` fixture truth from protected main. Stale duplicate free-pool and branch-coverage deltas therefore disappeared from the effective PR diff. Temporary `source-fix-1589*` writer workflows are absent from the candidate; no temporary writer is part of the production mechanism. Only fresh evidence for the post-repair exact head is eligible for merge.

## Rollback

Rollback the strict public admission layer, private Noema review core, taxonomy validator/prompt contract, CodeGraph loader/helper integration, observed-probe regression suites, focused quality workflow, doctoring, and product-gap traceability together. Do not retain tests that require `probe_kind` or evidence-bearing comments while reverting production parsing/admission. Protected-main deleted-file context, routing policy, free-pool fixture truth, and unrelated control-plane repairs are not owned by this increment and must not be rolled back with it.

## References

GitHub. (2026). *About pull request reviews*. GitHub Docs. https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/reviewing-changes-in-pull-requests/about-pull-request-reviews

National Institute of Standards and Technology. (2022). *Secure Software Development Framework (SSDF) Version 1.1: Recommendations for mitigating the risk of software vulnerabilities* (NIST SP 800-218). https://doi.org/10.6028/NIST.SP.800-218

OWASP Foundation. (2021). *OWASP Code Review Guide, version 2.0*. https://owasp.org/www-project-code-review-guide/
