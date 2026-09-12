# Strix final-report integrity

## Symptom and evidence

`contextual-orchestrator#1156` head `45e94744` produced central Strix run
`34706522798`, artifact `10302770755`. The Strix job succeeded, but its SARIF
had no results and the 307-byte final report contained only the four
`finish_scan` argument descriptions. The matching `run.json` still recorded
`status: completed`, `scan_completed: true`, and `success: true`.

The published Linux wheel for `strix-agent==1.5.3` had SHA-256
`ba0b6b13f13f41e45f3eb4dba515641d1bc71363ca6e758d0cd05c20ff56b6ea`.
Isolated execution of that wheel's `strix/tools/finish/tool.py::_do_finish`
showed the cause: it rejects blank sections but accepts the four schema
descriptions verbatim and persists them as a completed scan. No model, network,
credential, or real target scan was used in the reproduction.

## Repair boundary

The central `scripts/ci/strix_quick_gate.sh` now inspects only newly created,
regular `run.json` files before accepting child exit 0. It normalizes whitespace
and rejects a report when any final section exactly matches that section's
known upstream schema description. It does not impose a minimum length, require
invented findings, or reject an empty SARIF by itself. Upstream repair
[`usestrix/strix#1305`](https://github.com/usestrix/strix/pull/1305), commit
`5394c79`, adds the same semantic guard at `_do_finish` and binds its regression
cases to the generated tool schema. Until a verified release
carries that change, the central gate remains the organization-wide enforcement
point.

## Reproduction and verification

Run from the repository root:

```bash
STRIX_TEST_CASE_FILTER=schema-description-echo-fails \
  bash scripts/ci/test_strix_quick_gate.sh
STRIX_TEST_CASE_FILTER=substantive-zero-finding-report-succeeds \
  bash scripts/ci/test_strix_quick_gate.sh
```

The first case writes the exact four descriptions with completed/success flags
and requires a fail-closed gate verdict. The second writes a substantive
zero-finding report and requires success. A saved report, empty SARIF, or child
exit code alone is never exact-head security-review evidence.

## Failed approaches and prevention

- Blank-only validation fails because schema descriptions are non-empty.
- A byte or word-count threshold can reject concise, valid zero-finding reports
  and still admit long filler.
- Treating every empty SARIF as failure would erase valid no-finding outcomes.
- Consumer repositories must not copy this check. Keep it in the central gate
  and remove it only after a pinned upstream release proves equivalent behavior.
