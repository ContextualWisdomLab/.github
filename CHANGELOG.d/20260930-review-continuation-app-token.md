# Fixed

- Route bounded Noema and Strix consumer-repository transport continuations to
  the central `.github` dispatcher with the existing OIDC-exchanged organization
  GitHub App token, failing closed before the POST when that authority is absent.
