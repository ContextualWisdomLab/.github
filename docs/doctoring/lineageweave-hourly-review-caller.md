# LineageWeave hourly review-repair caller

The central repository owns the bounded hourly review-repair caller for
`ContextualWisdomLab/LineageWeave`. It invokes the reusable scheduler with the
explicit all-base selector because LineageWeave uses stacked pull requests,
inspects at most 50 open pull requests, and dispatches at most one repair per
heartbeat. Merge automation remains protected-`main`-only in the separate
central merge scheduler.

LineageWeave uses minute `4`, which is reserved for this product in the shared
heartbeat registry. Minute `47` belongs to Inkspan and must not be reused here.
The caller preserves an in-flight repair and waits two hours before retrying
the same exact head.

The reusable scheduler remains fail-closed: the organization variable
`OPENCODE_REPOSITORY_DISPATCH_TARGETS` must contain the exact target
`ContextualWisdomLab/LineageWeave`, and the forwarded scheduler credentials
must be available. A missing allowlist entry or mutation credential is an
operational configuration action, not a reason to weaken the workflow.

The repair worker reviews and proposes source changes only. Required checks,
independent approval, unresolved-thread policy, protected merge, release, and
rollback remain governed by the target repository and central merge scheduler.
