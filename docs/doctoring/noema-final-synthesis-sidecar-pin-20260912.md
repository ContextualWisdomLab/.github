# Noema final-synthesis sidecar pin repair

## Incident and boundary

ContextualWisdomLab/.github PR #2052 at
`68daf0f61d2afc0ebf68aa260713b2e481f5112d` ran Required Noema Review
`34688188671`, job `103539568718`. Credential selection, installation-token
minting, OIDC exchange, exact-head validation, and sidecar startup completed.
The verdict request failed after 582.0 seconds with HTTP 502,
`phase=response_error`, and served model
`deepseek-ai/deepseek-v4-flash-0731`.

Artifact `10296722291` (`noema-sidecar-evidence`) records 24 candidates, 16
probes, five ready routes, two deferred routes, and nine rejected routes. Its
sanitized stderr shows attempts across both
`deepseek-ai/deepseek-v4-flash-0731` and
`deepseek-ai/deepseek-v4-pro-0813`, plus circuit open, reset, and clear events.
Therefore the caller's `attempts=1` means one Noema request; it does not mean
the gateway tried one provider route. A caller retry, direct-provider fallback,
or longer wrapper timeout would duplicate gateway ownership.

The job log binds the runtime source to
`414f22973658c4ddc3d4320fcf7acd9b4e8ba991`. That immutable source reproduces
a final-synthesis `ProviderUpstreamError` instead of trying an eligible free
sibling. The exact protected-main merge for contextual-orchestrator PR #1094,
`9334dc91aaf853b758077e983517a822b6b21edb`, passes the same regression. The
incident log does not name the terminal internal agent role, so this is a
reproduced deployed-source defect, not conclusive phase attribution.

## Repair

Advance only the central sidecar's immutable CO pin and its contract-test/ADR
mirror. Do not change model timeout, provider selection, the
`orchestrator/free` identifier, caller attempts, or credential scope. Merge
`9334dc91` is an ancestor of protected main
`012beaacd0631f8cd3391c77744eeb626269b5de` at verification time.

Both old and new revisions carry the same `requirements.lock` SHA-256:
`c80752a4c6bbbc1bc9b0cb2b938831693a88dfdca7d1130bb4c00e2f9fe21345`.
The sidecar installs that file with `--require-hashes --no-deps`; it does not
install the project's mutable dependency graph from `pyproject.toml`.

## Verification

- Old source: identical final-synthesis eligible-free-sibling regression fails.
- New source: generated-planner no-entry and final-synthesis regressions pass;
  `test_review_gateway.py` reports 13 passed.
- New source with the central exact invocation: import/startup contract passes,
  including local HTTP 413 handling, accepted bodies above 64 KiB, byte-exact
  tool descriptions, and cleanup. Startup-body SHA-256 is
  `3dc3b5bffb95f90ba9ef1db1dbe93003def994e4d063637420ed9bbe0645b178`.
- Central pin/ADR/baseline contracts report 34 passed in 2.32 seconds. The full
  central Python suite reports 3,035 passed, one skipped, and 36 subtests in
  227.88 seconds; `bash -n` and `git diff --check` also pass.
- No live provider call or release was performed. Hosted checks on the updated
  #2052 head and a qualifying independent review remain required.

## Reproduction rule

For a future sidecar failure, recover the vendored SHA from the job log and the
bounded route trace from the failure artifact. Reproduce against that immutable
tree, compare it with a protected-main owner fix, verify identical locked
dependencies and the central startup contract, then advance the pin. Keep
incident attribution unknown when the telemetry does not name the terminal
internal phase.
