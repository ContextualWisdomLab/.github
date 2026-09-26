### Noema and Strix report the full orchestrator/free candidate trail on failure

- New `scripts/ci/sidecar_route_trail.py` reads the already-sanitized sidecar stderr log and prints
  one `SIDECAR_CANDIDATE_TRAIL` notice listing every candidate the last serving request tried, in
  order, with a bounded outcome label (`http_<status>`, `timeout`, `disconnect`, `invalid_response`)
  and elapsed seconds. Noema run 36166447802 reported `HTTP 429 provider_capacity_unavailable` after
  1041.5 s, but its trail was: two NVIDIA gemma-4-31b routes (disconnect after 526.9 s, 504 after
  302.1 s), four NVIDIA llama/muse routes with unusable responses, and only then the two deferred
  OpenRouter routes that answered 429. The gateway's final status reflects only the last candidate.
- `noema-review.yml` runs the summary in a failure-only step before the sidecar evidence upload;
  `strix.yml` runs it just before `STRIX_PROVIDER_UNAVAILABLE`. Both call the trusted base copy,
  skip a missing or symlinked script, and ignore its exit status.
- Diagnostic only: gate verdicts, exit codes, and the transport-retry eligibility derived from the
  gateway HTTP status are unchanged.
