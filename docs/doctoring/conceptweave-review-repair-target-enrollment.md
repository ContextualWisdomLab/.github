# ConceptWeave bounded review-repair target enrollment

Date: 2026-09-20

## Problem

`ContextualWisdomLab/ConceptWeave` has valid exact-head review findings but was absent from the protected central `hourly-review-repair.yml` target lookup and from the source-controlled mirror of `OPENCODE_REPOSITORY_DISPATCH_TARGETS`. Mention-triggered OpenCode is review-only, so an `@opencode-agent` comment is not a source-writer handoff. The edit-capable owner remains the central `pr_review_fix_scheduler.py -> pr-review-autofix.yml` path.

ConceptWeave PR #46 exact `974972e2885baa956af9b728fee158b1782704d1` is the concrete consumer case: its executable relation-kind/index-ownership RED needs a bounded same-head writer, not a second product-local workflow.

## Decision

Enroll ConceptWeave in the existing consolidated central recovery caller instead of creating a repository-local caller or widening review-agent permissions.

The existing `59 16 * * *` daily missed-event recovery is shared with `semantic-data-portal`. The matrix keeps separate `target_repository` and `concurrency_group` values, so sharing the trigger does not merge product ownership or cancellation leases. ConceptWeave uses protected base `main`, `retry_hours = 2`, `max_dispatches = 1`, and the existing central scheduler/autofix implementation.

The source-controlled dispatch-target mirror also includes the exact `ContextualWisdomLab/ConceptWeave` repository name. The live repository variable remains a separate deployment prerequisite because source control cannot mutate that configuration by itself.

## RED -> repair trace

- Protected base: `.github/main@e6334e229581a918e2f22de18733b76fa65d7e71`.
- RED commit: `b530783d09a656fe4ddc324243dd15de193eee86` adds `tests/test_conceptweave_review_repair_target.py`; protected source contains neither the caller target nor mirror entry, so the contract is unsatisfied before enrollment.
- Mirror repair: `a84da81b6a7e822923f3414379db9072a4c41fde`.
- Consolidated caller repair: `18109ca0b84a554caafe1e72f18cf52e74a0c3cf`, minimized by ordinary-forward successor `796adc4393b6e83553ad330afc38e52a3b1544dd`.
- Existing consolidated-caller contract is extended on the same branch so schedule resolution and the dispatch-target mirror remain one acceptance surface.

No product-local `conceptweave-hourly-review-repair.yml` is introduced. No provider/model/group override, paid fallback, workflow-token write grant, approval, merge, release, protection mutation, or source-neutral wake is added.

## Acceptance and rollout boundary

Source acceptance requires the focused caller contracts and repository workflow validation to pass on the exact PR head. Runtime acceptance additionally requires all of the following after protected integration:

1. `OPENCODE_REPOSITORY_DISPATCH_TARGETS` in `ContextualWisdomLab/.github` contains the exact `ContextualWisdomLab/ConceptWeave` entry and is re-read after mutation.
2. An unchanged-head ConceptWeave canary with an autofixable file-scoped review finding produces a central `PR Review Autofix ContextualWisdomLab/ConceptWeave#...@<sha>` worker.
3. The worker revalidates the live PR/head/base before model work and before publication, writes only sealed reviewed paths, and ordinary-forwards the same head branch.
4. A stale-head canary fails closed before publication. Queued, cancelled, or failed checks are never normalized into success.
5. ConceptWeave contains no duplicate local review-repair workflow.

Until those conditions are observed, enrollment is Proposed rather than operationally Accepted. Source GREEN cannot substitute for the live repository-variable update or canary evidence.

## Rollback

If the central caller causes target-specific admission or isolation regressions, remove only the ConceptWeave matrix entry and mirror entry, restore the previous exact target set, and leave the product repository unchanged. Do not replace the rollback with a local writer. If the live allowlist variable was updated, remove the same exact ConceptWeave entry there in the same rollback and re-read the variable before declaring rollback complete.
