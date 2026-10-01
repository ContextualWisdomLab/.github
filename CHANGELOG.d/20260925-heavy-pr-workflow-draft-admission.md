### Heavy required PR workflows skip Draft admission

- Security Scan, SAST Semgrep, and CodeQL PR skip their first
  runner-consuming job for Draft PRs only in native `.github` runs; ruleset
  launches bypass the Draft condition because they do not re-enter on
  `ready_for_review`. Python Security and Agent Review Runtime Quality retain
  their direct-run Draft guards.
- Native `.github` runs re-enter on `ready_for_review`.
- `converted_to_draft` creates a runner-free replacement generation while
  existing PR concurrency cancellation retires the prior Ready work.
- Push, schedule, and repository-dispatch paths remain unchanged.
