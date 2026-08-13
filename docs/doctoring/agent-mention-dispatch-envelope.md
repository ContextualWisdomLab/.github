# Agent-mention dispatch envelope

## Decision

Materialize accepts only exact SHA-256 pins or a bounded relative `-r` include; a lone `--require-hashes` line is not lock evidence.

Mention-triggered OpenCode review uses a three-property versioned claim
envelope instead of a 14-property snapshot dump. The scheduler validates
live head, base, and target-branch identity before enqueueing. A stale
snapshot cannot enter merge mutations or cancel a newer scheduler,
OpenCode, or Strix run.

The OpenCode repository-dispatch workflow serializes valid sender/PR
groups with `cancel-in-progress: false` and `queue: max` so a delayed
stale event cannot replace a pending newer head. Strix cannot combine
that queue key with its pull-request cancellation policy; it isolates
default-branch dispatch by run id instead (GitHub, n.d.). NIST SP 800-53
Rev. 5 SC-23 requires session authenticity so an old claim cannot hijack
a later review (National Institute of Standards and Technology, 2020).

## References

GitHub. (n.d.). *Control the concurrency of workflows and jobs*. GitHub
Docs. Retrieved August 13, 2026, from
https://docs.github.com/en/actions/using-jobs/using-concurrency

National Institute of Standards and Technology. (2020). *Security and
privacy controls for information systems and organizations* (NIST SP
800-53 Rev. 5). https://doi.org/10.6028/NIST.SP.800-53r5
