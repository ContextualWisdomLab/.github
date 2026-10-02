### Changed

- Fail closed on malformed, control-bearing, or multiline OIDC and GitHub App
  credentials in the Strix metadata exchange and proposed Strix and Noema
  continuation adapters. All fields now admit only the exact ASCII token
  alphabet `[A-Za-z0-9._-]+`; actual-shell fixtures cover NUL, SOH, and BEL
  before Authorization, masking, or output. The invalid consumer `github.token`
  fallback remains removed, and Noema HTTP error responses close after bounded
  telemetry extraction. Cross-repository dispatch remains blocked on the
  immutable Noema owner capability tracked by `ContextualWisdomLab/noema#735`.
