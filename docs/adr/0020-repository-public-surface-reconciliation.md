# ADR-0020: Reconcile repository public surfaces from reviewed desired state

- **Status:** Accepted
- **Date:** 2026-09-01
- **Scope:** ContextualWisdomLab organization repository-facing metadata and classification

## Context

Repository descriptions, topics, GitHub Pages settings, DeepWiki badges, and issue/PR labels are customer- and maintainer-visible product surfaces. The connected automation client can read these surfaces but does not expose every repository-settings mutation directly. Repeated one-off edits also create drift, casing mistakes, duplicate badges, contradictory Pages intent, and inconsistent labels.

The organization therefore needs one auditable owner for the desired state and one convergent reconciliation path. README prose remains owned by each product repository because it must be reviewed together with that product's actual behavior. Repository settings and cross-repository label normalization belong in the organization control plane.

## Decision

1. `config/repository-metadata.json` is the reviewed desired state for exact repository casing, concise public descriptions, normalized topics, exact DeepWiki intent, and GitHub Pages intent.
2. `config/repository-label-taxonomy.json` defines the small semantic label vocabulary and explicit repository/issue assignments. The reconciler manages only labels named by that vocabulary and preserves unrelated priority, status, area, and workflow labels.
3. `scripts/ci/reconcile_repository_metadata.py` applies description, topics, and Pages settings only after repository-local preconditions are present on the protected default branch. It aggregates repository failures so one blocked leaf does not prevent independent repositories from being attempted.
4. `scripts/reconcile_repository_labels.py` applies only reviewed label assignments. It is idempotent and aggregates assignment failures for the same non-blocking fleet behavior.
5. DeepWiki README content is not mutated centrally. `deepwiki: true` requires the exact linked badge on the default branch before metadata writes; `deepwiki: false` fails closed while that exact badge is still present so desired state cannot silently contradict the public README.
6. Pages uses GitHub's legacy branch source on the repository default branch at `/docs`. Creation occurs only when no site exists; update occurs only when branch, path, or build type differs; disable deletes an existing site. A converged Pages site receives no hourly write.
7. Pull-request execution is read-only validation. Privileged reconciliation runs only from trusted `.github/main`, uses the existing maintainer credential, does not widen pull-request tokens, and does not bypass repository rulesets or reviews.
8. Scheduled and manual applies share one ref-scoped concurrency lane and do not cancel an active apply midway. Partial fleet state is therefore completed by the active run rather than being abandoned by a replacement run.
9. Repository-wide tests, focused 100% statement/branch coverage for both reconciliation scripts, docstring gates, manifest/taxonomy validation, and `git diff --check` are required before apply can run.

## Consequences

- Public metadata becomes declarative, reviewable, repeatable, and convergent instead of depending on ad-hoc connector capabilities.
- A leaf repository can block only its own unsafe mutation; other eligible repositories continue in the same invocation.
- Exact README and Pages preconditions make a source commit insufficient evidence of publication. Live repository metadata and Pages state must be re-read after apply before publication is claimed.
- Explicit label assignments intentionally favor evidence over broad title heuristics. Expanding classification coverage requires a reviewed assignment or a separately justified deterministic classifier.
- The privileged token must retain only the repository-administration/Pages/issue permissions required by the declared fleet. Credential values never enter the manifest or logs.

## Rejected alternatives

- **Report missing connector mutations without repair.** Rejected because the organization owns a GitHub Actions/API control plane that can safely provide the capability.
- **Mutate README badges from the central control plane.** Rejected because that would bypass the active product writer and make customer-facing content independent of product review.
- **Rewrite Pages every hour.** Rejected because a converged desired-state reconciler must have a write-free steady state.
- **Infer issue type from title prefixes alone.** Rejected because classification needs evidence and must preserve richer repository-local workflow labels.
