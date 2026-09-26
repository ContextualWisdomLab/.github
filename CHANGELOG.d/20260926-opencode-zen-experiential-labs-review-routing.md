### OpenCode Zen and Experiential Labs reach the review sidecars

- The Noema, OpenCode review dispatch, and Strix sidecar steps pass
  `OPENCODE_ZEN_API_KEY` and the Experiential Labs key under both its
  canonical (`EXPERIENTIAL_LABS_API_KEY`) and legacy
  (`EXPERIENTAL_LABS_API_KEY`) spellings. The two spellings are aliases of one
  credential (`zdr_policy.PROVIDER_CREDENTIAL_ALIASES`); the sidecar counts
  them once in its "provider credentials present" log.
- The sidecar bootstrap, launcher credential detection, and free-pool
  admission (`FREE_POOL_CREDENTIAL_NAMES`) accept those credentials.
  `zdr_policy` adds provider URLs, auth schemes, and credential names for
  `opencode_zen`, `opencode_go`, and `experiential_labs`, and scopes all
  three as non-ZDR (no zero-retention attestation), so they never serve
  private-repository reviews under `CONTEXTUAL_ORCHESTRATOR_REQUIRE_ZDR`.
- The vendored contextual-orchestrator pin advances from
  `767e67fbc6b881a452761f32abb69b9971b9b03b` to
  `098ea168aabfd27ceb1696b2da001bd9d134782e` (the merge of
  ContextualWisdomLab/contextual-orchestrator#1145, 687 commits), which adds
  `experiential_labs` discovery at `api.experientiallabs.ai`. Behaviour the
  bump brings in: the old 15 s per-HTTP-call discovery socket timeout
  (`DISCOVERY_TIMEOUT_SECONDS`) is now unset by default, and each provider's
  whole catalog discovery instead runs on its own daemon thread bounded by a
  30 s `PROVIDER_DISCOVERY_DEADLINE_SECONDS` deadline (an abandoned thread may
  outlive that deadline until its socket returns or the process exits);
  `requires-python` rises to `>=3.12`; and `provider_bootstrap` selects by
  exact `model_group`. Refs ContextualWisdomLab/.github#2377.
