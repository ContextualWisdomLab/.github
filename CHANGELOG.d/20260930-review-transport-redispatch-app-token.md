### Fixed

- Exchange required-workflow OIDC for a repository-scoped GitHub App token
  before Strix and Noema continuations dispatch to `ContextualWisdomLab/.github`;
  remove the invalid consumer `github.token` fallback and close Noema HTTP error
  responses after bounded telemetry extraction.
