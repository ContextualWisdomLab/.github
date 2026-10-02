# Review catalog input-modality evidence

## Verified boundary defect

The central sidecar independently converts discovered models into a review
catalog. `_report_rows` omitted `input_modalities`; `parse_discovery_report`
also discarded it; catalog agents therefore had no `input:<modality>` tags.
The pinned gateway has no separate agent modality field and consumes those tags
when distinguishing blind text traffic from mixed text/image review traffic.

The incident lead is
[fast-mlsirm#2052](https://github.com/ContextualWisdomLab/fast-mlsirm/pull/2052)
head `3fe6d77ff719c07a6a022c81edfb73e747ed4a7c`, whose Noema
[job 109266241557](https://github.com/ContextualWisdomLab/fast-mlsirm/actions/runs/36515522775/job/109266241557)
reported HTTP 400. The metadata-loss defect is independently reproduced; the
specific provider rejection and this defect's causality for that job remain
unconfirmed until a new same-target-head run supplies evidence. HTTP 400 is not
converted into capacity retry, approval, or an elapsed-time failure verdict.

## Minimal repair

Carry input evidence through the existing report and policy boundary, validate
its scalar/list/tuple shape, normalize nonempty string values and duplicates,
and persist it as the gateway's existing input tags. Unknown/missing evidence
retains legacy behavior; malformed evidence fails closed instead of silently
becoming unknown. Price, credential binding, ZDR, route priority and model
identity remain unchanged. No modality-specific route is removed at discovery.

The earlier [#1529](https://github.com/ContextualWisdomLab/.github/pull/1529)
provided the original input-requirement investigation. Its blanket text-only
filter is not copied because the current gateway also accepts figure-bearing
reviews. Its unrelated scheduler-test deltas have not been audited for complete
carryover, so this repair does not authorize closing #1529 as superseded.

## Evidence

- RED: 11 failures and two legacy passes across source-to-catalog and malformed
  evidence cases before the repair.
- GREEN: 211 related tests; 13 focused cases also pass with `GITHUB_ACTIONS=true`.
- Policy statement/branch coverage: 100%, 198 statements and 74 branches.
- Both edited production modules: 100% docstrings.
- Offline composition against the actual gateway admission predicates from
  `contextual-orchestrator@01bf92a3ec67a0e1f9b68978eb16b60301e985fd`:
  text-only evidence admits general text, not mixed-image traffic; text+image
  evidence rejects blind text but admits mixed-image review; image-only evidence
  admits neither mixed text/image nor blind text. This uses the pinned predicate
  source, not a replacement routing heuristic. No provider request is made.
- Full-suite retry on code head `92389c1cf` finished with 5,176 passed, five
  skipped, 40 subtests passed and one failure in 912.52 seconds. The unchanged
  `test_bare_origin_reproduces_the_route_not_found_outage` observed the expected
  wrong route, but the installed CLI did not render `not found` before the
  fixture stopped it. Its two CLI cases passed separately in 47.70 seconds.
  The first full attempt was interrupted at ten minutes. These are incomplete
  whole-suite acceptance, not failures invented from a model inference timer.
- Hosted current-head verification and independent approval remain required;
  no provider HTTP 400 resolution, model verdict or approval is fabricated.

## Ownership

The Air session explicitly retains its coverage/approval workflow changes and
its separate `rust_changed_packages.py` selector work. This lane owns only the
review launcher report, policy catalog conversion, and corresponding regressions.
No library calculation, GPU, manuscript, release assembly or publication changes
are included.
