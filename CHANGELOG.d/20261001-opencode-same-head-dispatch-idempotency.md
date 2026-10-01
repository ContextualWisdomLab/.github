### Fixed

- Preserve any active exact-head OpenCode dispatch across all GitHub admission
  states when the required-check wake path is retried, fail closed on ambiguous
  inventory, avoid GitHub's lossy pending concurrency replacement, retire only
  live-head-verified older central runs with completion evidence, and revalidate
  pull-request authority immediately before a new dispatch.
