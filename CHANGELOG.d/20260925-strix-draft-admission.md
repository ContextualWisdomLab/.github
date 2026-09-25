### Strix skips Draft pull-request admission

- Native `.github` Draft `pull_request_target` generations now skip Strix
  metadata and scanning jobs without a runner; ruleset-launched runs in other
  repositories always admit them because those runs do not re-trigger on
  `ready_for_review`. Native `ready_for_review` creates the fresh exact-head
  scan.
- Non-Draft PR pushes, forced `repository_dispatch`, push, and scheduled scans
  remain admitted. `converted_to_draft` still cancels the prior Ready
  generation through workflow concurrency without admitting a cleanup runner.
- The synchronous model job remains intentionally unbounded under the
  repository's progress-based Strix occupancy policy.
