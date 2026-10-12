### Stale CodeQL/OpenCode dispatches end as a notice instead of failing

- `codeql-scan-dispatch.yml` (`validate-dispatch`) and `opencode-review-dispatch.yml`
  (`validate-pr-metadata`) now retire a dispatch whose target pull request is closed, or whose
  live head has moved strictly past the dispatched head, with a `::notice::`, a step-summary
  line and a `stale=true` output. A head mismatch alone is not enough: the compare API
  (`repos/{target}/compare/{dispatched}...{live}`) must answer `status: ahead` with
  `behind_by: 0`, proving the live head descends from the dispatched one and therefore gets
  its own dispatch. A lagging API that still serves the previous head right after a push
  (`behind`), a force-push (`diverged`), or a failed or malformed compare keeps the original
  fail-closed `head_sha` mismatch, so a fresh head is never skipped. The CodeQL `scan` matrix (and therefore `settle-required-run`)
  and the OpenCode coverage-materialization steps, `coverage-evidence` and `opencode-review`
  skip on that output, so the run concludes success instead of failure. Under runner-queue
  saturation the newer dispatch for the same pull request is itself queued, so workflow-level
  `cancel-in-progress` could not retire the stale run before it started.
- Still fail-closed: dispatch authorization and payload validation (checked first), a failed or
  malformed live pull-request lookup, base ref/SHA or head ref disagreement at the same head,
  cross-fork metadata, and the later privileged re-validation steps. Draft state is not treated
  as stale because ruleset-launched required workflows do not re-dispatch on `ready_for_review`.
- The OpenCode side keeps retirement behind `EVENT_NAME == repository_dispatch` because its
  dispatch authorization and supplied-head binding are nested under that check; the CodeQL
  side needs no such guard because it triggers only on `repository_dispatch` and authorizes
  unconditionally before the live lookup.
