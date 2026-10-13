### Central review source survives transient GitHub archive failures

- Required Noema, Required OpenCode, and the PR review merge scheduler now use
  bounded native `curl` retries when materializing the immutable trusted
  `.github` source archive. Authentication, exact-SHA binding, extraction, and
  fail-closed behavior are unchanged.
