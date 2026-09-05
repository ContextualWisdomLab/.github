# Hourly free-pool policy fixture RCA — 2026-09-01

## Scope

Protected `main` at `960b08456de4c87a5a833938220d6d83f68d61c1` failed `Hourly NVIDIA NIM Review Repair` run `33498263904`, job `99825357734`, in step `Verify hourly scheduler and NVIDIA NIM autofix contracts`.

## Exact failure evidence

The hosted pytest run produced two deterministic failures in `tests/test_contextual_orchestrator_review_policy.py` and then missed the 100% policy coverage gate:

- `test_build_catalog_applies_account_cap` still expected two `openai` rows to be admitted to the default `orchestrator/free` pool and raised `KeyError: 'openai'` after the rows were correctly excluded.
- `test_build_catalog_respects_limit` constructed its twenty free candidates entirely from `openai`; the post-#1587 policy correctly rejected that free-pool source set and raised `PolicyError: no free model route is available ... orchestrator/free would fail closed`.

The failure is therefore stale test-fixture evidence, not a product regression, provider/network transient, permission failure, or expected governance failure. The triggering protected-main commit is merge commit `960b08456de4c87a5a833938220d6d83f68d61c1` from PR #1587, whose intended contract keeps all provider credentials globally discoverable while admitting only `BYTEZ_API_KEY`, `NVIDIA_NIM_API_KEY`, `NVIDIA_NIM_API_KEY_SUB`, and `OPENROUTER_API_KEY` sources to `orchestrator/free`. PR #1587 added dedicated credential-boundary regressions but did not update these two older generic policy fixtures.

## Smallest repair

Change only the two generic fixtures so the behaviors they are intended to test—per-account limiting and total catalog limiting—use an authorized free-pool provider (`openrouter`) instead of the deliberately excluded `openai` source. No production policy, warning, security gate, review gate, coverage threshold, or fail-closed behavior is changed.

RED evidence is the protected-main run above. The repair commit is `7190562128067983c864fd56a3c4c13ea345a351`; compare against protected main is exactly three additions and three deletions in one test file.

## Related but separate blocker

Open PR #1591 is not a safe substitute for this fixture repair. Although its exact-head hourly self-test currently succeeds, unresolved independent review evidence shows that its admission-only catalog can return more than twelve agents while `contextual_orchestrator_review_launcher._bounded_fallback_catalog_limit()` still rejects `primary_count > 12`, aborting sidecar startup. That production-path issue must be repaired and re-reviewed separately rather than bypassed to make protected main green.

## Verification

Hosted exact-head Checks on the repair PR are authoritative. After merge, rerun the failed protected-main workflow and re-fetch the exact protected-main Checks. Pending, queued, skipped, or stale predecessor evidence is not treated as success.
