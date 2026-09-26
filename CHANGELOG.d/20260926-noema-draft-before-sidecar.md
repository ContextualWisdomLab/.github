### Noema checks live draft state before provisioning the orchestrator sidecar

- `noema-review.yml`'s `noema-review` job provisioned the contextual-orchestrator review
  sidecar (10-13 minutes) before `two_phase.py --prepare-verdict-file` read the live PR and
  printed `PR is draft; Noema verdict preparation skipped.`, so every draft run held a runner
  for ~13 minutes and produced nothing (newsdom-api job 108077744310 on 2026-09-25, `.github`
  job 106665379126 on 2026-09-22) while the organization's Actions concurrency is saturated.
  A new `live_draft` step, placed after `Validate current pull request head` / `Resolve Noema
  target repository visibility`, reads the live PR with the same reviewer token and REST lookup
  and gates sidecar provisioning, the HWP document reader, and `Prepare Noema model verdict` on
  `steps.live_draft.outputs.live_draft != 'true'`. The decision stays runtime-only (no trigger
  filter, no `github.event.pull_request.draft`), fails open to today's full path on a lookup
  error, leaves `noema_prepare` outputs unset so publication stays skipped exactly as before,
  and the job still concludes success for drafts. Ruleset-launched runs in other repositories
  keep identical outcomes: a draft never produced a Noema verdict at runtime; only the check
  moved earlier. `tests/test_noema_draft_admission_before_sidecar.py` pins ordering, gating,
  and the fail-open step behavior; `docs/doctoring/noema-draft-before-sidecar.md` records the
  rationale.