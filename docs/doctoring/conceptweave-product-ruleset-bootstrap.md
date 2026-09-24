# ConceptWeave Product ruleset bootstrap

## Decision

ConceptWeave owns its Product acceptance workflow; `.github` owns the privileged GitHub governance mechanism that can make that repository-owned result merge-blocking. The Product check therefore remains repository-local while this control-plane code manages only the repository-scoped policy around it.

The live state observed on 2026-09-23 has one inherited ruleset, organization ruleset `18156473`, and no ConceptWeave-owned ruleset. Protected ConceptWeave `main@f4f440dd58c77d7cd90dff8a1eb2eeb9a9940425` does not contain `.github/workflows/product.yml`. PR `ContextualWisdomLab/ConceptWeave#35@2f3bc5851e4c02ac9d4f038bb9e816f0e3ba2788` introduces that producer, but its exact-head Actions inventory consequently contains only central required workflows and no repository-owned Product run.

That ordering creates a bootstrap constraint. Activating a required `Product acceptance` status before #35 lands would require a result that the protected base cannot emit. The correct lifecycle is staged rather than bypassed.

## Lifecycle

1. Review this source on top of canonical ruleset-governance owner PR `.github#1644`. The initial manifest deliberately carries `ruleset_id: null` because no repository ruleset exists yet.
2. After #1644 and this dependent source have reached protected `.github/main`, an authorized maintenance run may create the ConceptWeave repository ruleset only in GitHub's `evaluate` enforcement state. Creation is bound to the exact protected control-repository SHA and the dedicated `ruleset-governance-maintenance` environment/credential.
3. The created positive ruleset ID is then adopted into `config/conceptweave-product-ruleset.json` through ordinary review. An already-existing unpinned rule is never silently adopted by a later mutation.
4. Separately, #772/#1351/#1644 must remove the structurally unsatisfiable generic human-approval requirement and routine administrator bypass without weakening central workflow, thread, deletion, or non-fast-forward protections.
5. #35 may then land normally under the existing protected central controls. This is the one-time producer bootstrap boundary; an administrator bypass, synthetic status, or fabricated reviewer is not an acceptable shortcut.
6. With Product present on protected ConceptWeave `main`, Foundation `ContextualWisdomLab/ConceptWeave#1` (or another substantive current-base successor) supplies the activation canary. The canary must be open and non-draft, target the exact current protected `main`, and have an exact-head terminal-success repository-owned `Product` run whose `Product acceptance` job and check-run belong to the same check suite.
7. Activation derives the positive GitHub App integration ID from that real successful check rather than guessing it. The ruleset is promoted from `evaluate` to `active` with exactly one required status: `Product acceptance`. `Product metadata-only` is intentionally excluded because metadata-only PR edits skip the Product validation job.
8. After activation, a substantive canary head transition is used to observe the ordinary merge path while Product is pending and then successful. The merge remains blocked while the new exact-head Product result is absent/pending/failed and may satisfy only the Product gate after terminal success. Central security/review/thread requirements continue to apply independently.

## Safety boundary

The reconciler discovers repository-owned rulesets with inherited parents excluded and rejects duplicate exact-name matches or foreign provenance. It never places the ConceptWeave-only status into the organization-wide ruleset.

Privileged mutations require `CWL_RULESET_RECONCILE_ENABLED=true`, a distinct `CWL_RULESET_ADMIN_TOKEN`, the protected `ruleset-governance-maintenance` environment, and an exact `.github/main` SHA. Activation reuses #1644's immutable-history verification, ambiguous-PUT settlement, and compensating collision recovery instead of maintaining a second weaker update algorithm. Privileged runs are serialized and non-cancellable during the mutation/recovery critical section.

Creation is intentionally narrower than activation. A successful or transport-ambiguous POST must converge to one exact-name repository-owned ruleset with the reviewed `evaluate` payload; bootstrap then verifies its latest immutable history state. Further mutation is refused until that new ruleset ID is committed to reviewed source.

Activation additionally proves the Product producer from GitHub itself: live PR head/base, current protected base ref, Product workflow content at that base, exact run identity/status/conclusion, run-to-PR binding, exact `Product acceptance` job, matching check suite, successful check-run, and positive check-app ID. Predecessor runs, `Product metadata-only`, another check suite, stale base, Draft PR, or an inherited ruleset cannot satisfy activation.

## Evidence and standards

GitHub's repository ruleset API exposes `evaluate` and `active` enforcement and supports repository ruleset creation/update under Administration write authority. Required status check rules support an `integration_id`, allowing the active rule to bind the observed GitHub Actions producer rather than only a textual context. This source keeps the binding absent during evaluate bootstrap because no protected-base Product check exists yet; the ID is introduced only from the live canary at activation.

Control intent maps to NIST SP 800-53 Rev. 5 AC-6 (least privilege) and CM-3 (configuration change control): privileged credentials remain separated from normal PR execution, mutations are exact-source-bound and reviewed, and live configuration changes are independently re-read and history-checked. The repository-specific Product gate complements, rather than replaces, the organization-wide review/security controls.

## Verification

The focused contract suite exercises manifest rejection, exact repository discovery, evaluate creation and ambiguous-create settlement, source adoption, evaluate/active verification, protected-base Product presence, stale/malformed canary rejection, run/job/check-suite/app binding, concurrent policy drift, normal activation history verification, ambiguous activation settlement, and CLI privilege boundaries.

Before this source is treated as accepted, run the focused suite with branch coverage against `scripts/ci/reconcile_conceptweave_product_ruleset.py`, require 100% statement/branch coverage and 100% interrogate docstrings, run `git diff --check`, and then repeat on the eventual current-main descendant after #1644 has been reconciled. Historical GREEN from this dependent branch does not transfer across that restack.

Refs: `.github#2348`, `.github#1644`, `.github#772`, `.github#1351`, `ContextualWisdomLab/ConceptWeave#35`, `ContextualWisdomLab/ConceptWeave#1`, `ContextualWisdomLab/ConceptWeave#4`.
