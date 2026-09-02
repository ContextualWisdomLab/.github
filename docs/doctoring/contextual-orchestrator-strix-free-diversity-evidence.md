# Doctoring record: evidence-gated path toward `orchestrator/free` for Strix

- **Date:** 2026-08-30
- **Subject:** The 2026-08-30 owner directive asks that Noema, OpenCode, and
  Strix all route review through `contextual-orchestrator`'s `orchestrator/free`
  pool. Noema and OpenCode already do (`docs/adr/0003-contextual-orchestrator-vendored-free-zdr.md`).
  Strix does not, and stays on `orchestrator/auto` today; this record explains
  why the pin was not flipped on the strength of the instruction alone, and
  what new evidence infrastructure exists so a future, properly reviewed change
  can flip it safely.
- **Decision record:** [`docs/adr/0003-contextual-orchestrator-vendored-free-zdr.md`](../adr/0003-contextual-orchestrator-vendored-free-zdr.md)
  (2026-08-30 addendum)
- **Related:** [`docs/product-goal-directive.md`](../product-goal-directive.md) §8
  and its Follow-up findings note; [`docs/doctoring/noema-orchestrator-free-zdr.md`](noema-orchestrator-free-zdr.md)

## Why this needed reconciliation, not a direct edit

`docs/product-goal-directive.md` states its own conflict policy: "Where this
directive and those documents conflict, resolve the conflict and update
whichever document is wrong — do not silently pick one." Strix's
`orchestrator/auto` pin is not an oversight; it is an accepted ADR-0003
decision backed by a specific, dated finding: on 2026-08-29, the DiskSage
exact-head scan showed every discovered free route sharing the OpenRouter
outage domain, so a strict `orchestrator/free` pin for Strix (which has no
provider fallback) would have gone dark on that one provider's outage. Silently
flipping the pin today, on the strength of a general instruction that does not
re-examine that finding, would reintroduce the exact single-point-of-failure
risk the ADR was written to avoid — for the workflow whose job is the org's
required *security* review. Silently keeping the old pin, on the other hand,
would ignore a legitimate cost/consistency goal the owner restated today.

## What changed

`scripts/ci/contextual_orchestrator_review_policy.py`'s
`build_zdr_prioritized_catalog` now reports `free_family_diversity`: the count
of distinct outage-domain provider families (`provider_family`; the primary
and secondary NVIDIA NIM keys already collapse into one family) among *all*
discovered free routes, independent of which `--pool` was requested. This is
new evidence, not a new decision — it is computed from the same discovery
report the catalog already validates, and it is present whether the caller
asked for `--pool free` or `--pool auto`.

`tests/test_contextual_orchestrator_review_policy.py` gained
`test_build_catalog_reports_free_family_diversity` (asserts diversity of 4 for
the existing five-provider fixture) and
`test_build_catalog_reports_single_family_free_concentration` (a regression
test reproducing the 2026-08-29 shape: two NVIDIA keys only, which collapse to
one family, so diversity is 1). Full suite: 1882 passed, 1 skipped; coverage
of the changed module remains 100% (`coverage run -m pytest tests` +
`coverage report --include=scripts/ci/contextual_orchestrator_review_policy.py`).

`.github/workflows/strix.yml` is unchanged in this PR. It still hard-pins
`CONTEXTUAL_ORCHESTRATOR_POOL: auto` and its `STRIX_MODEL`/`STRIX_LLM` gates
still reject anything except `orchestrator/auto`.

## What has to happen before Strix can move to `orchestrator/free`

A follow-up PR to `strix.yml` (or to
`scripts/ci/contextual_orchestrator_review_sidecar.sh`, whichever the
implementer finds is the correct evidence-read point) should read
`free_family_diversity` from the sidecar's `policy-report.json` after
discovery and select `orchestrator/free` only when it is `>= 2` — i.e. the
discovered free catalog spans at least two independent outage domains, so one
provider's outage cannot black out Strix's required review — and fall back to
`orchestrator/auto` otherwise. That PR was deliberately not bundled into this
one because `strix.yml` is a `pull_request_target` required workflow
(`docs/pr-review-and-merge-procedure.md`'s trust-boundary note: PRs that edit
trusted review workflows run the *base branch's* trusted scripts and can fail
their own checks until the base branch catches up) and its `STRIX_MODEL`
allowlist is a deliberate hardened gate, not an oversight to route around in
the same change that adds the evidence it would depend on.

## Audit trail

- `docs/adr/0003-contextual-orchestrator-vendored-free-zdr.md` — 2026-08-30
  addendum recording the decision and rationale.
- `docs/product-goal-directive.md` §8 and its Follow-up findings note — the
  directive text and prior CodeRabbit reconciliation this addendum extends.
- `scripts/ci/contextual_orchestrator_review_policy.py`,
  `tests/test_contextual_orchestrator_review_policy.py` — the evidence change
  and its tests.
