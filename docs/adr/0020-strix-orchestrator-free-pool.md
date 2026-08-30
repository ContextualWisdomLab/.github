# ADR-0020: Retire Strix's separate `orchestrator/auto` pool

- Status: accepted
- Date: 2026-08-30
- Scope: ContextualWisdomLab/.github central Strix security-review pipeline
  (`.github/workflows/strix.yml`)
- Supersedes: [ADR-0003](0003-contextual-orchestrator-vendored-free-zdr.md)
  Decision §4's Strix-specific `orchestrator/auto` wiring only. Every other
  part of ADR-0003 (vendoring, discovery, ZDR-first policy, the
  provider-family-diverse catalog, the sidecar contract) is unchanged and
  remains binding.
- Decision: Strix security analysis now routes through the same fail-closed,
  zero-cost `orchestrator/free` pool that OpenCode and Noema already use.
  `CONTEXTUAL_ORCHESTRATOR_POOL` in `strix.yml` is `free`, not `auto`.
  Zero Data Retention (ZDR)-compliant routing for private targets is
  unchanged and remains mandatory.
- Ownership: `.github` owns this control-plane decision;
  `ContextualWisdomLab/contextual-orchestrator` owns the gateway's catalog
  and routing behavior referenced as evidence below.
- Figma File ID: N/A (no customer UI).

## Context

ADR-0003 put Strix on a separate `orchestrator/auto` pool instead of
`orchestrator/free`, citing a 2026-08-29 exact-head DiskSage scan that found
four discovered free routes all sharing the OpenRouter outage domain — i.e.
one provider family. All three CI consumers (OpenCode, Noema, Strix) are
otherwise standardized on the vendored `contextual-orchestrator` gateway; the
product decision behind this ADR is to standardize the pool too, unless doing
so would reopen the exact single-family-concentration risk ADR-0003 flagged.

This ADR was written after actually reading
`scripts/ci/contextual_orchestrator_review_policy.py`, not assuming its
behavior — see Verification below.

## Verification: does the family-diversity cap already protect `orchestrator/free`?

**Yes, mechanically identically to `orchestrator/auto` — this was already true
before this change, it did not need to be added.**

`build_zdr_prioritized_catalog()` in
`scripts/ci/contextual_orchestrator_review_policy.py` takes a `pool` argument
(`"free"` or `"auto"`) that controls only which rows are *candidates*:

```python
candidate_rows = (
    all_free_rows if pool == "free" else [*all_free_rows, *all_priced_rows]
)
```

Every later step — ZDR admission, sort order, and critically the per-family
cap —

```python
per_family: Counter[str] = Counter()
picked: list[Mapping[str, Any]] = []
for row in eligible_rows:
    family = provider_family(str(row["provider"]))
    if per_family[family] >= family_cap:
        continue
    per_family[family] += 1
    picked.append(row)
```

runs identically regardless of `pool`. There is no `if pool == "auto"` branch
anywhere near the family cap. `scripts/ci/contextual_orchestrator_review_sidecar.sh`
confirms this at the wiring level too: it exports
`ORCHESTRATOR_CATALOG_FAMILY_CAP` (default 4, from
`ORCHESTRATOR_CATALOG_FAMILY_CAP`/`DEFAULT_FAMILY_CAP`) **before** pool
selection, and passes the same `--family-cap` value to the policy CLI whether
`CONTEXTUAL_ORCHESTRATOR_POOL` resolves to `free` or `auto`. Nothing in this
PR changed the cap or its wiring, because nothing needed to: it already
applied to `orchestrator/free`'s catalog construction the same way it applies
to `orchestrator/auto`'s.

### What the cap does and does not buy

The cap bounds **overrepresentation**: no more than `family_cap` (4) picked
routes may come from one provider family
(`scripts/ci/zdr_policy.py`'s `PROVIDER_FAMILIES` groups only
`nvidia_nim`/`nvidia_nim_sub` together; `openrouter`, `openai`, and `bytez`
are each their own family). It cannot **manufacture** a family that has no
candidate rows to begin with. If, at discovery time, every currently
zero-priced route across the five credentialed providers happens to come from
a single family, the cap has nothing to trim and nothing else to substitute
in — the resulting `orchestrator/free` catalog is exactly as concentrated as
an `orchestrator/auto` catalog would be under the same discovery snapshot,
because both pools share the identical capping logic operating over
different-sized candidate sets.

This is precisely the shape of the 2026-08-29 DiskSage finding ADR-0003 cites:
four free routes, all one family (`family_cap` default is 4, so the cap would
not have trimmed anything even if it had already been pool-uniform back
then — there was no other family among the free candidates to admit instead).

### What has changed since that finding

Two things reduce, without mathematically eliminating, this risk:

1. **Broader free-route provenance.** As recorded in the 2026-08-30
   `docs/product-technical-gap-baseline.md` entries ("orchestrator/free pool
   exhausted by upstream ZDR hardening" and its follow-up), the vendored
   `contextual-orchestrator` pin advanced to `30c6d716…`, which includes
   `ContextualWisdomLab/contextual-orchestrator#919`: the Models.dev
   free-cost cross-reference that used to attest `is_free` only for
   `opencode_zen` now also covers `nvidia_nim`, `nvidia_nim_sub`, and
   `openai`. That widens how many distinct provider families can plausibly
   surface a genuinely zero-cost route in the *free* candidate set at any
   given discovery run — the free pool is no longer structurally dependent on
   OpenRouter alone the way it was on 2026-08-29.
2. **The family cap was already pool-uniform**, as verified above — so this
   migration does not trade away a protection Strix used to have. Strix gets
   exactly the same family-diversity enforcement on `/free` that it had on
   `/auto`.

Neither point is a guarantee. Which providers currently publish a $0 tier is a
live market condition, not a code invariant; a future discovery run could
still find only one free-priced family, in which case `orchestrator/free`
(for Strix, OpenCode, and Noema alike) would admit a concentrated catalog. The
gateway's per-request behavior when a selected route errors is a *different*
axis from catalog-time family diversity and is not what the cap addresses at
all — see Residual risk below.

## Decision detail

- `strix.yml`'s "Gate Strix secrets", "Provision contextual-orchestrator Strix
  sidecar", and "Prepare Strix model input file" steps now use
  `contextual-orchestrator/orchestrator/free` / `CONTEXTUAL_ORCHESTRATOR_POOL:
  free` in place of `.../orchestrator/auto` / `auto`. The dispatch-payload
  override allowlist (`github.event.client_payload.strix_llm`) is narrowed to
  the same set of accepted spellings for `orchestrator/free`; no other model
  string is newly reachable.
- `STRIX_FALLBACK_MODELS: ""` is unchanged — Strix still has no
  external/direct-provider fallback of its own. Provider discovery and
  failover remain entirely delegated to the gateway.
- `CONTEXTUAL_ORCHESTRATOR_REQUIRE_ZDR` wiring for private targets is
  unchanged: private/internal scans still require an attested ZDR-only
  catalog and fail closed rather than admitting a non-ZDR route, exactly as
  strict as before this change.
- No change to `scripts/ci/contextual_orchestrator_review_policy.py` or
  `scripts/ci/contextual_orchestrator_review_sidecar.sh`'s family-cap wiring:
  per Verification above, none was needed.

## Residual risk (documented, not hidden)

Two distinct risks are in play; conflating them would misdiagnose either one:

1. **Catalog-time family concentration.** Reduced by the Models.dev
   generalization above but not eliminated by any code guarantee — the cap
   protects against overrepresentation among the families that exist in a
   given discovery snapshot, not against a snapshot that happens to contain
   only one free-priced family. This is a live-market condition, tracked the
   same way for Strix as it already was for OpenCode/Noema; it is not a new
   exposure this migration introduces; it is `orchestrator/free`'s existing,
   already-accepted risk profile now shared by a third consumer.
2. **Request-time failover, a separate axis.** Independently of this PR, live
   `noema-review` job logs across recent `.github` PRs show
   `orchestrator/free` preflight succeeding but the actual chat-completion
   request against the selected route returning HTTP 502 (following, in
   several logs, a Bytez discovery HTTP 500 and a 413 "request too large"),
   recurring across a majority of the last ~15 `noema-review` runs. This
   looks like a gateway request-time-failover gap — the selected route errors
   and the gateway does not retry the next discovered free route — not a
   catalog-composition problem, and not something `family_cap` or the
   Models.dev change addresses. A dedicated fix for this is in progress
   directly in `ContextualWisdomLab/contextual-orchestrator` (out of this
   repository's scope). Strix moving onto `orchestrator/free` inherits
   whatever reliability this gap currently has — the same as OpenCode and
   Noema already do today — so this migration is parity with the org's
   already-accepted standard, not a new class of exposure. It is called out
   here explicitly rather than folded into the family-diversity discussion
   above, because the two are different mechanisms with different fixes.

Neither risk is a reason to withhold this migration: the product decision
this ADR implements is explicit or the standard now, and Strix already had no
better protection from `orchestrator/auto` against the request-time failover
axis (that pool depends on the same gateway request path).

## Consequences

- All three central CI review/security consumers (OpenCode, Noema, Strix) are
  now on one pool, one credential-scope story, and one fail-closed guarantee.
  There is one fewer distinct "which pool does X use" fact to keep in sync
  across `AGENTS.md`, ADRs, doctoring records, and contract tests.
- `orchestrator/auto` is not deleted from
  `scripts/ci/contextual_orchestrator_review_policy.py` or
  `scripts/ci/contextual_orchestrator_review_sidecar.sh` — it remains a
  supported, tested pool value (default `free`) for any future consumer that
  needs priced-route fallback; only `strix.yml`'s selection changed.
- Cost profile: Strix now shares the zero-cost guarantee. If the free pool's
  live catalog is ever empty (see the 2026-08-30 gap-baseline "root-cause
  fix" entries for the historical case where it briefly was, org-wide,
  before an upstream fix), Strix fails closed exactly like OpenCode/Noema —
  no security scan runs rather than a silently degraded or paid one.

## References

- ADR-0003 (superseded in part; see its Amendment section).
- `docs/product-technical-gap-baseline.md`, 2026-08-30 entries: "orchestrator/free
  pool exhausted by upstream ZDR hardening" and "orchestrator/free root-cause
  fix landed; sidecar pin bumped" (Models.dev cross-reference generalization
  and the `_fetch_json` User-Agent fix, `ContextualWisdomLab/contextual-orchestrator#919`).
- `scripts/ci/contextual_orchestrator_review_policy.py` (family-cap
  implementation, read in full for this ADR).
- `scripts/ci/contextual_orchestrator_review_sidecar.sh` (`ORCHESTRATOR_CATALOG_FAMILY_CAP`
  export ordering, read in full for this ADR).
