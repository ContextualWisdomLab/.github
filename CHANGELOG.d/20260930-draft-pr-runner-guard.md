## Changed

- Draft pull requests no longer take a control-runner slot for the OpenCode,
  Strix, CodeQL PR and merge-scheduler entry jobs. They previously ran only to
  conclude that a draft needs no verdict; marking the pull request ready runs
  them again on the same head. Noema is unchanged because it reads the live
  draft state.
- A `converted_to_draft` event now enters the existing per-PR concurrency
  group for CodeQL PR, SAST Semgrep, Security Scan, and Python Security. The
  event cancels an older queued same-PR run, while every entry job skips before
  runner admission. This closes the queue-retention gap without weakening any
  Ready-head security check.
