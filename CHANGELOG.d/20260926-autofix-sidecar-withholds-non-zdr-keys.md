### Autofix sidecar withholds non-ZDR provider keys

- `.github/workflows/pr-review-autofix.yml` no longer passes
  `OPENCODE_ZEN_API_KEY` or either Experiential Labs key
  (`EXPERIENTIAL_LABS_API_KEY` / legacy `EXPERIENTAL_LABS_API_KEY`) to its
  contextual-orchestrator sidecar. That step sets no
  `CONTEXTUAL_ORCHESTRATOR_REQUIRE_ZDR` visibility gate (the sidecar default is
  `false`), and neither provider has a ZDR attestation, so private repository
  code could otherwise reach non-ZDR providers. The visibility-gated sidecars
  (Noema, OpenCode review dispatch, Strix) keep all three keys. Contract tests
  pin the split.
- Experiential Labs deliberately stays in `FREE_POOL_CREDENTIAL_NAMES`: its
  account moves between free and paid over time, so free-pool admission must
  follow model-discovery evidence rather than a static credential exclusion.
  A discovery-level "servable free now" signal is tracked as a follow-up.
  Refs ContextualWisdomLab/.github#2377.
