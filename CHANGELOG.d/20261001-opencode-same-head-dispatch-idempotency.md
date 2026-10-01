### Fixed

- Preserve any active exact-head OpenCode dispatch across all GitHub admission
  states when the required-check wake path is retried, fail closed on ambiguous
  inventory, avoid GitHub's lossy pending concurrency replacement, retire only
  live-head-verified older central runs with completion evidence, and revalidate
  pull-request authority immediately before a new dispatch. After a receiver
  acquires the exact-PR lease, revalidate live authority and the formal
  exact-head review receipt again so a completed prior receiver cannot trigger
  duplicate coverage or model execution.
  Preserve exact-head merge-scheduler admissions within GitHub's documented
  `queue: max` bound; a dedicated metadata-only cleanup inventories every
  active state twice across all PR-associated scheduler triggers,
  rejects incomplete GitHub search results, retires only
  live-head-revalidated predecessor runs, and proves each accepted
  cancellation reaches `completed/cancelled`.
