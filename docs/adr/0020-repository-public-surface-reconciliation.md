# ADR-0020: Reconcile repository public surfaces from reviewed desired state

- **Status:** Accepted
- **Date:** 2026-09-01
- **Scope:** ContextualWisdomLab organization repository-facing metadata and classification

## Context

Repository descriptions, topics, GitHub Pages settings, DeepWiki badges, and issue/PR labels are customer- and maintainer-visible product surfaces. The connected automation client can read these surfaces but does not expose every repository-settings mutation directly. Repeated one-off edits also create drift, casing mistakes, duplicate badges, contradictory Pages intent, and inconsistent labels.

The organization therefore needs one auditable owner for the desired state and one convergent reconciliation path. README prose remains owned by each product repository because it must be reviewed together with that product's actual behavior. Repository settings and cross-repository label normalization belong in the organization control plane.

## Decision

1. `config/repository-metadata.json` is the reviewed desired state for exact repository casing, concise public descriptions, normalized topics, exact DeepWiki intent, and GitHub Pages intent. `pages_mode` is optional; omitted means the established legacy `/docs` mode, while `pages_mode: workflow` explicitly preserves an existing Actions-backed deployment.
2. `config/repository-label-taxonomy.json` defines the small semantic label vocabulary and explicit repository/issue assignments. The reconciler manages only labels named by that vocabulary and preserves unrelated priority, status, area, and workflow labels.
3. `scripts/ci/reconcile_repository_metadata.py` applies description, topics, and Pages settings only after repository-local preconditions are present on the protected default branch. It aggregates repository failures so one blocked leaf does not prevent independent repositories from being attempted.
4. `scripts/ci/reconcile_repository_labels.py` applies only reviewed label assignments. It mutates taxonomy-managed labels through individual label endpoints, is idempotent, preserves unrelated concurrent labels, and aggregates assignment failures for the same non-blocking fleet behavior.
5. DeepWiki README content is not mutated centrally. `deepwiki: true` requires the exact linked badge on the default branch before metadata writes; `deepwiki: false` fails closed while that exact badge is still present so desired state cannot silently contradict the public README.
6. Pages has two explicit ownership modes. Legacy mode requires the repository default branch to contain the regular file `docs/index.md`; absent legacy sites may be created at `/docs`, drifted legacy sites may be updated, and converged sites receive no write. Workflow mode requires the regular file `.github/workflows/pages.yml` on the protected default branch **and** an already-existing live Pages configuration with `build_type: workflow`. The central reconciler never creates or converts a workflow-backed site. Those workflow-mode source and live-configuration preconditions are validated before description, topic, or Pages mutation so an invalid workflow declaration cannot leave a partially applied metadata record.
7. Contents API source probes are type-aware. A successful response satisfies a required-source precondition only when the response is a single object with `type: file`; a directory object or directory listing is not accepted as reviewed file evidence.
8. Pull-request execution is read-only validation. Privileged reconciliation runs only from trusted `.github/main`, uses the existing maintainer credential, does not widen pull-request tokens, and does not bypass repository rulesets or reviews.
9. Reconciliation runs from the trusted hourly schedule and exposes no branch-selectable `workflow_dispatch` entrypoint. Pull-request validation keeps a PR-stable concurrency lineage and cancels superseded validation runs; trusted scheduled protected-main apply remains non-cancellable so a replacement heartbeat cannot abandon a partially updated fleet.
10. Metadata and label lanes retain independent exit statuses during apply: label reconciliation still runs after an aggregated metadata failure, and the job fails afterward if either lane failed.
11. Repository-wide tests, focused 100% statement/branch coverage for both reconciliation scripts, docstring gates, manifest/taxonomy validation, and `git diff --check` are required before apply can run.

## Consequences

- Public metadata becomes declarative, reviewable, repeatable, and convergent instead of depending on ad-hoc connector capabilities.
- A leaf repository can block only its own unsafe mutation; other eligible repositories continue in the same invocation.
- Exact README and Pages preconditions make a source commit insufficient evidence of publication. Live repository metadata and Pages state must be re-read after apply before publication is claimed.
- Actions-backed Pages can be enrolled without silently rewriting a repository's reviewed deployment architecture to legacy `/docs`.
- Workflow-mode failure is fail-before-write for the repository record: missing workflow source, missing Pages, or a non-workflow live build type prevents description/topic mutation as well as Pages mutation.
- Explicit label assignments intentionally favor evidence over broad title heuristics. Expanding classification coverage requires a reviewed assignment or a separately justified deterministic classifier.
- The privileged token must retain only the repository-administration/Pages/issue permissions required by the declared fleet. Credential values never enter the manifest or logs.

## Rejected alternatives

- **Report missing connector mutations without repair.** Rejected because the organization owns a GitHub Actions/API control plane that can safely provide the capability.
- **Mutate README badges from the central control plane.** Rejected because that would bypass the active product writer and make customer-facing content independent of product review.
- **Convert workflow-backed Pages to legacy `/docs` for uniformity.** Rejected because deployment ownership is a reviewed product boundary; reconciliation must preserve an explicitly declared Actions-backed deployment rather than rewrite it.
- **Treat any successful Contents API response as file evidence.** Rejected because a directory can exist at the same path and must not satisfy a regular-file precondition.
- **Expose branch-selected manual dispatch.** Rejected because the central control-plane contract requires manual entrypoints not to load branch-selected code.
- **Replace an issue's entire label list.** Rejected because stale read-modify-write can erase unrelated labels added concurrently by humans or automation.
- **Rewrite Pages every hour.** Rejected because a converged desired-state reconciler must have a write-free steady state.
- **Infer issue type from title prefixes alone.** Rejected because classification needs evidence and must preserve richer repository-local workflow labels.
