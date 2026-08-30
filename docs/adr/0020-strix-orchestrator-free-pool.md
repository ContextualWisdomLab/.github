# ADR-0020: Evidence-gated `orchestrator/free` for Strix

- Status: accepted
- Date: 2026-08-30
- Scope: ContextualWisdomLab/.github central Strix security-review pipeline
  (`.github/workflows/strix.yml`)
- Refines (does not supersede): [ADR-0003](0003-contextual-orchestrator-vendored-free-zdr.md)
  Decision §4's Strix-specific `orchestrator/auto` wiring. Every other
  part of ADR-0003 (vendoring, discovery, ZDR-first policy, the
  provider-family-diverse catalog, the sidecar contract) is unchanged and
  remains binding. `orchestrator/auto` is **not retired**: it is the
  permanent, load-bearing fallback this ADR's conditional falls back to.
- Depends on: [`ContextualWisdomLab/.github#1433`](https://github.com/ContextualWisdomLab/.github/pull/1433),
  which added the `free_family_diversity` evidence this ADR's gate reads.
  This ADR is the follow-up #1433's own description named as the intended
  next step.
- Decision: `strix.yml`'s model-resolution step reads `free_family_diversity`
  (the count of distinct outage-domain provider families among all
  discovered free routes, computed on every discovery run by
  `scripts/ci/contextual_orchestrator_review_policy.py`) from the sidecar's
  policy report and selects `contextual-orchestrator/orchestrator/free`
  **only when that count is `>= 2`**. In every other case — including 0, 1,
  or any evidence that is missing, unreadable, or malformed — it falls back
  to `contextual-orchestrator/orchestrator/auto`, the same
  provider-diverse, priced-fallback pool ADR-0003 originally pinned Strix
  to. Zero Data Retention (ZDR)-compliant routing for private targets is
  unchanged and remains mandatory regardless of which pool is selected.
- Ownership: `.github` owns this control-plane decision;
  `ContextualWisdomLab/contextual-orchestrator` owns the gateway's catalog,
  routing, and request-time failover behavior referenced as evidence below.
- Figma File ID: N/A (no customer UI).

## Context

ADR-0003 put Strix on a separate `orchestrator/auto` pool instead of
`orchestrator/free`, citing a 2026-08-29 exact-head DiskSage scan that found
four discovered free routes all sharing the OpenRouter outage domain — i.e.
one provider family. A same-date product directive asked that Strix route
through `orchestrator/free` like OpenCode and Noema already do.

**This ADR is a correction, not the first attempt.** An initial PR
(`ContextualWisdomLab/.github#1437`, first draft) flipped `strix.yml`'s pool
unconditionally to `orchestrator/free`, reasoning that the family-diversity
cap already applied identically to both pools and so no new protection was
needed. A human exact-head governance review on that draft rejected it:

> The source itself acknowledges that the 2026-08-29 single-family
> outage-domain condition is not eliminated, that provider diversity is only
> a live-market possibility, and that request-time failover remains broken.
> A per-family cap does not create a second family. Moving required Strix
> from the correctness-first `orchestrator/auto` pool to `orchestrator/free`
> before current evidence proves at least two independent available families
> therefore reintroduces the exact availability regression ADR-0003 was
> adopted to prevent.

The cap bounding overrepresentation among *existing* families cannot
manufacture a second family that was never discovered in the first place —
exactly the 2026-08-29 shape (four free routes, one family, cap default 4:
the cap has nothing to trim and nothing to substitute). An unconditional flip
would have made Strix's required security review depend on a single
provider's uptime, with no fallback, which is a worse outcome than the rare
priced-fallback call `orchestrator/auto` already prefers to avoid.

The review also identified a canonical evidence owner already in flight:
[`ContextualWisdomLab/.github#1433`](https://github.com/ContextualWisdomLab/.github/pull/1433),
which added `free_family_diversity` to
`scripts/ci/contextual_orchestrator_review_policy.py` without changing
`strix.yml`, explicitly naming the wiring below as its intended follow-up.
This ADR is that follow-up, built on #1433's branch (merged into this one)
rather than a duplicate reimplementation.

## Acceptance criteria (from the review) and how each is met

1. **Protected-main discovery evidence reports at least two independently
   credentialed/provider-family free routes** before Strix may run on
   `orchestrator/free`. *Met by construction*: the gate reads
   `free_family_diversity` from this run's own sidecar discovery — never a
   cached or assumed value — and requires `>= 2` before selecting the free
   pool. See "Residual risk" below for what this evidence can and cannot
   promise about future runs.
2. **A negative fixture proves diversity 0/1 retains `orchestrator/auto`**
   rather than weakening availability. *Met*:
   `tests/test_strix_contextual_orchestrator_contract.py::test_diversity_of_zero_or_one_stays_on_orchestrator_auto`
   executes the workflow's own "Resolve Strix model from free-route
   diversity evidence" step (extracted directly from the tracked YAML, the
   same behavioral-testing pattern already used for the neighboring "Gate
   Strix secrets" step) with diversity 0 and 1 and asserts the resolved
   model stays `contextual-orchestrator/orchestrator/auto`. A companion test
   (`test_missing_or_malformed_evidence_fails_closed_to_auto`) proves the
   same for a missing file, unreadable JSON, a missing field, a non-integer,
   a negative integer, and a boolean value — every failure mode fails closed
   to `orchestrator/auto`, never `orchestrator/free`.
   `scripts/ci/strix_required_workflow_smoke.sh`'s
   `assert_free_pool_gated_by_diversity` additionally proves this
   *structurally* against the tracked workflow text itself: the free-pool
   literal may appear only inside the diversity-threshold conditional, the
   safe `orchestrator/auto` default must be set before that conditional is
   evaluated, and no other code path may assign the free pool.
3. **Request-time route failure demonstrably advances to another admitted
   route, or returns typed non-passing provider evidence.** *Pending,
   tracked outside this repository, stated honestly rather than assumed*:
   see "Request-time failover: current status" below.
4. **Unchanged exact-head Strix canaries produce authoritative reports.**
   *Verified structurally, not by a live run this PR does not perform*: see
   "Strix canary mechanism" below.
5. **The unrelated direct-NIM dead-code/docs cleanup is split or adopted by
   its actual owner** instead of being bundled into this policy transition.
   *Met*: extracted onto
   `claude/noema-opencode-strix-orchestration-sexqzc-nim-cleanup` as its own
   draft PR against `main`, removed from this PR/branch.

## Why the sidecar still boots the `auto` catalog

`strix.yml`'s "Provision contextual-orchestrator Strix sidecar" step sets
`CONTEXTUAL_ORCHESTRATOR_POOL: auto` unconditionally — **not** `free` — even
though the resolved model might end up being `orchestrator/free`. This is
required, not merely conservative: `contextual_orchestrator_review_launcher.py`
only loads priced fallback agents into the running orchestrator when it boots
with `--pool auto`; booting `--pool free` loads free-tagged agents exclusively.
If the sidecar booted free-only, a later request for the model name
`orchestrator/auto` would resolve against the exact same single-family free
catalog under a different name — a fake fallback that would silently defeat
this entire gate. Booting `auto` keeps a genuine, price-attested fallback
tier loaded and ready regardless of which model name Strix ends up
requesting; `_require_pool_model` in the vendored `contextual_orchestrator.server`
serves `orchestrator/free` as the free-tagged subset of that same loaded
catalog when requested, and `free_family_diversity` is computed identically
either way (see `build_zdr_prioritized_catalog`'s docstring).

## Decision detail

- `strix.yml`'s "Gate Strix secrets" step keeps its static base model at
  `contextual-orchestrator/orchestrator/auto` (the safe default) and its
  dispatch-override allowlist unchanged from ADR-0003 (`orchestrator/auto`
  spellings only — `orchestrator/free` is never a caller-requested override,
  only an automatic, evidence-gated upgrade).
- A new "Resolve Strix model from free-route diversity evidence" step runs
  after the sidecar is provisioned (so `CONTEXTUAL_ORCHESTRATOR_EVIDENCE`,
  the sidecar's policy-report path, is available) and before the model is
  written to the Strix input file. It reads `free_family_diversity`,
  defaults `resolved_model` to the gate's own base model, and upgrades to
  `contextual-orchestrator/orchestrator/free` only inside a
  `free_family_diversity >= 2` conditional. Any exception reading or parsing
  the evidence (missing file, invalid JSON, missing/wrong-typed field)
  degrades to diversity `0` with a `::warning::` annotation — it never
  raises the job, and it never upgrades on unproven evidence.
- "Prepare Strix model input file" now accepts both
  `contextual-orchestrator/orchestrator/auto` and
  `contextual-orchestrator/orchestrator/free` (previously only one literal
  was valid, matching whichever pool was statically pinned at the time).
- `STRIX_FALLBACK_MODELS: ""` is unchanged — Strix still has no
  external/direct-provider fallback of its own. Provider discovery and
  failover remain entirely delegated to the gateway.
- `CONTEXTUAL_ORCHESTRATOR_REQUIRE_ZDR` wiring for private targets is
  unchanged: private/internal scans still require an attested ZDR-only
  catalog and fail closed rather than admitting a non-ZDR route, exactly as
  strict as before this change, under either resolved pool.
- No change to `scripts/ci/contextual_orchestrator_review_policy.py`'s
  family-cap logic beyond #1433's additive `free_family_diversity` field;
  the cap itself was already pool-uniform (see ADR-0003's Amendment).

## Request-time failover: current status

A separate, orthogonal reliability gap exists independently of catalog-time
family diversity: live `noema-review` job logs across recent `.github` PRs
have shown `orchestrator/free` preflight succeeding but the actual
chat-completion request against the selected route returning HTTP 502,
consistent with the gateway not failing over to the next discovered free
route at request time when the primary one errors. `family_cap` and
`free_family_diversity` do not address this axis at all — they describe the
catalog the gateway builds, not what it does when a request against an
already-admitted route fails.

**As of this PR, that fix has not been confirmed merged.** Investigation for
this PR found an in-progress, not-yet-opened-as-a-PR commit in a local
`contextual-orchestrator` checkout titled "fix(routing): classify primary
provider transport failures explicitly," describing exactly this class of
misclassification (a generic upstream 5xx/429/network error being
routed through a tool-execution-oriented heuristic instead of the provider
taxonomy's own retryable flag, which could stop `orchestrator/free` and
`orchestrator/auto` request-time failover on a request that never touched a
tool). That commit is **not** part of any open pull request found via GitHub
search or repository listing as of this PR, and it is **not** an ancestor of
`contextual-orchestrator`'s `origin/main` (verified with `git merge-base
--is-ancestor`). It therefore cannot be treated as landed evidence — it is
reported here only as the clearest signal available that a fix is in
progress, consistent with what this repository's task instructions already
anticipated. This repository's vendored pin
(`ORCHESTRATOR_PIN_SHA` in `scripts/ci/contextual_orchestrator_review_sidecar.sh`,
currently `30c6d71680e659f25a0a433d4726ad0d437f9757`) is **not** bumped by
this PR — a security-relevant vendored-pin bump is a separate,
independently reviewable change once the fix actually merges, not a rider on
this policy transition.

Strix moving onto `orchestrator/free` under the `>= 2` diversity condition
inherits whatever request-time reliability the gateway currently has — the
same as OpenCode and Noema already do unconditionally today. This is not a
new exposure this ADR introduces; it is a known, tracked limitation of the
pool Strix now conditionally shares, stated here rather than assumed
resolved.

## Strix canary mechanism

The review required "unchanged exact-head Strix canaries [to] produce
authoritative reports." This repository's doctoring records use "canary" to
mean a real, executed protected-main run that starts the corrected code path
and reaches a genuine result — not a named, dedicated workflow file. For
Strix specifically, the closest matching mechanism found is `strix.yml`'s own
`push` trigger on `branches: [main, develop, master]` (with a `paths-ignore`
for non-executable doc/image-only diffs), backstopped by a weekly
full-tree `schedule` run (`cron: '0 3 * * 1'`) that re-scans protected
branches with no path filter. Neither trigger's structure, path filters, or
concurrency group is changed by this PR — the new "Resolve Strix model"
step and its inputs are additive to the existing job, not a change to when
or how the job runs.

**This PR does not claim a live canary run was observed.** Confirming that
push-triggered run "produces an authoritative report" with this PR's
conditional gate in place requires a real merge to a protected branch, which
this PR's own instructions and this repository's governance model (merge
requires OpenCode approval via the mechanical scheduler) explicitly place
outside this session's authority. This is stated plainly rather than
assumed: the mechanism is identified and structurally unchanged; its
post-merge live behavior is unverified by this PR.

## Residual risk (documented, not hidden)

Two distinct risks remain, deliberately not conflated:

1. **Catalog-time family concentration, now gated rather than assumed
   away.** The `>= 2` threshold is real evidence recomputed every run, not a
   static claim — but a passing count today is not a guarantee for the next
   run. Which providers currently publish a $0 tier is a live-market
   condition: a future discovery run could still find only one free-priced
   family, in which case the gate correctly falls back to
   `orchestrator/auto` rather than admitting a concentrated
   `orchestrator/free` catalog. This is the entire point of gating on live
   evidence instead of a static pin — a diversity of 1 could not have been
   caught by #1437's original unconditional approach at all.
2. **Request-time failover, a separate axis** the diversity gate does not
   and cannot address (see above). Not yet confirmed fixed upstream as of
   this PR.

Neither risk blocks landing this ADR: it is strictly more conservative than
both the pre-existing static `orchestrator/auto` pin (which never captured
any upside when the free catalog *was* diverse) and #1437's rejected
unconditional flip (which ignored risk 1 entirely). It cannot, by
construction, regress below the availability ADR-0003 originally protected.

## Consequences

- Strix gains the zero-cost `orchestrator/free` pool exactly when evidence
  supports it, and loses nothing when evidence does not: `orchestrator/auto`
  remains the default, permanent fallback, not a route being phased out.
- `orchestrator/auto` is not deleted from
  `scripts/ci/contextual_orchestrator_review_policy.py` or
  `scripts/ci/contextual_orchestrator_review_sidecar.sh` — it remains the
  sidecar's boot-time pool for Strix unconditionally (see "Why the sidecar
  still boots the `auto` catalog" above) and a supported, tested pool value
  for any other consumer.
- Cost profile: Strix's per-run cost now varies with live free-route
  diversity instead of being fixed. When diversity is `>= 2`, Strix shares
  the zero-cost guarantee OpenCode/Noema already have; otherwise it retains
  `orchestrator/auto`'s existing priced-fallback cost profile, unchanged
  from before this ADR.
- One fewer static fact to keep in sync: `AGENTS.md`, this ADR, and the
  contract tests all describe the same evidence-gated mechanism instead of a
  pinned literal that would need updating every time the free catalog's
  composition changes.

## References

- ADR-0003 (refined, not superseded; see its Amendment section).
- [`ContextualWisdomLab/.github#1433`](https://github.com/ContextualWisdomLab/.github/pull/1433)
  (the `free_family_diversity` evidence this ADR's gate reads).
- [`ContextualWisdomLab/.github#1437`](https://github.com/ContextualWisdomLab/.github/pull/1437)
  (this ADR's own PR; its first draft was the rejected unconditional flip
  this ADR corrects).
- `scripts/ci/contextual_orchestrator_review_policy.py` (`free_family_diversity`
  computation, read in full for this ADR).
- `.github/workflows/strix.yml` ("Resolve Strix model from free-route
  diversity evidence" step).
- `scripts/ci/strix_required_workflow_smoke.sh` (`assert_free_pool_gated_by_diversity`).
- `tests/test_strix_contextual_orchestrator_contract.py` (the negative
  fixture and structural assertions).
