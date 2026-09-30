### Changed

- Fail closed on malformed or multiline OIDC and GitHub App credentials in the
  proposed Strix and Noema continuation adapter, remove the invalid consumer
  `github.token` fallback, and close Noema HTTP error responses after bounded
  telemetry extraction. Cross-repository dispatch remains blocked on the
  versioned Noema owner capability tracked by `ContextualWisdomLab/noema#735`.
