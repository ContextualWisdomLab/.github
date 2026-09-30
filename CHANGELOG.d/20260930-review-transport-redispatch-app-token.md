### Changed

- Fail closed on malformed, control-bearing, or multiline OIDC and GitHub App
  credentials in the proposed Strix and Noema continuation adapter. Both fields
  now admit only the exact ASCII token alphabet `[A-Za-z0-9._-]+`; actual-shell
  fixtures cover NUL and BEL before Authorization, masking, or output. The
  invalid consumer `github.token` fallback remains removed, and Noema HTTP
  error responses close after bounded telemetry extraction. Cross-repository
  dispatch remains blocked on the immutable Noema owner capability tracked by
  `ContextualWisdomLab/noema#735`.
