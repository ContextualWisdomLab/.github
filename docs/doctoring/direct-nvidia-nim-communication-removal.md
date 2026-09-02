# Doctoring record: removing the orphaned direct-NVIDIA-NIM model resolver

- **Date:** 2026-08-30
- **Subject:** `scripts/ci/select_nvidia_nim_model.py` made real, direct HTTPS calls to
  `integrate.api.nvidia.com` (bypassing the `contextual-orchestrator` gateway) to resolve a live
  model id. Two independent audits today — this PR's own, and `#1434`'s ZDR/pool-migration
  review — reached the same conclusion: zero callers anywhere in `.github/workflows/` or `scripts/`;
  only its own test exercised it. Removed as a small, standalone PR per the explicit request on
  `#1437`'s review thread to split direct-NIM cleanup out of the Strix pool-flip discussion.
- **Related:** `#1433` (`free_family_diversity` evidence), `#1434` (merged: Strix
  `orchestrator/free` flip + `family_cap` mitigation, whose own PR body flags this exact file as a
  "separate follow-up" rather than folding its removal into that PR), `#1437` (superseded pool
  migration proposal whose review thread asked for this split).

## What changed

- Removed `scripts/ci/select_nvidia_nim_model.py` and `tests/test_select_nvidia_nim_model.py`.
- `scripts/ci/contextual_orchestrator_review_sidecar.sh`'s `CATALOG_FAMILY_CAP` comment referenced
  this file by path as a worked example of a live-provider-catalog cross-check pattern a future,
  more complete fix could reuse; updated to point at this PR (`#1442`) instead of a path that no
  longer exists. A PR reference, not a raw pre-merge commit SHA or the removing branch's name, is
  used because a squash merge would leave a raw commit unreachable in plain git once the branch is
  deleted, while the PR and its full commit history stay permanently resolvable on GitHub.
- `docs/product-technical-gap-baseline.md`'s existing, dated historical entries describing this file
  (from `#1434`'s own investigation) are left as-is per this repo's "append a dated note,
  don't rewrite history" convention; a new §5.1 increment item records the removal itself.

## Why this is safe

The file's own docstring already described the mechanism it existed to avoid ("the scheduled autofix
worker used to hard-code one NVIDIA NIM model id... a single hard-coded id therefore turns a normal
provider lifecycle event into a total outage") in the past tense — the actual scheduled autofix
worker was already migrated to `contextual-orchestrator`'s own auto-discovery
(`discover_all_models()` / the review policy catalog) well before this removal, per ADR-0003. No
workflow YAML, no `scripts/ci/*.py`, and no `scripts/ci/*.sh` file referenced it by import, and no
production code path referenced it by path. Grepping the whole repository for
`select_nvidia_nim_model` after this removal returns historical doc mentions, this doctoring record,
and exactly one intentional code comment (`scripts/ci/contextual_orchestrator_review_sidecar.sh`'s
`CATALOG_FAMILY_CAP` note, which names the file on purpose as a searchable pointer to this PR's own
history, where a worked example of the pattern remains visible) — no executable reference remains.

## Audit trail

- `#1434` (merged) — independent corroboration this file is dead code, flagged as a follow-up
  rather than removed there.
- `#1437`'s review thread — the explicit request to split this cleanup into its own PR rather
  than bundle it with the pool-migration question.
- This PR's own diff — the removal itself.
