### Heavy required PR workflows skip Draft admission

- Security Scan, SAST Semgrep, CodeQL PR, Python Security, and Agent Review
  Runtime Quality now skip their first runner-consuming job while a PR is
  Draft and re-enter on `ready_for_review`.
- `converted_to_draft` creates a runner-free replacement generation while
  existing PR concurrency cancellation retires the prior Ready work.
- Push, schedule, and repository-dispatch paths remain unchanged.
