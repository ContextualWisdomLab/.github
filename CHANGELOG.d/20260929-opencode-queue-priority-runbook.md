## Added

- Operator runbook `scripts/ci/opencode_queue_priority.py` for the OpenCode
  review queue. It keeps PRs whose `review-priority` label was applied by a
  maintainer (a fork author cannot use it to jump the queue), reports backlog
  metrics, posts the cancel list to an issue before cancelling, and cancels
  only runs that are still queued.
