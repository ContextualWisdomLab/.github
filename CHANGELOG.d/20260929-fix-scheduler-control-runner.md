## Fixed

- Run the central review-fix scheduler's dispatch job on the idle control
  runners instead of the saturated hosted queue, where hourly repair runs had
  waited up to 12 hours. Only the central main caller is routed there; the job
  reads the GitHub API and dispatches autofix and never checks out pull-request
  content.
