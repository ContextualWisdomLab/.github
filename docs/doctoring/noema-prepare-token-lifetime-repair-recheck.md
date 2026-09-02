# Noema prepare-phase repair-retry recheck outliving its own token

## Incident and root cause

`ContextualWisdomLab/naruon#1503` (Required Noema Review, run `33489389355`, job
`100144610395`) failed with an opaque `gh: Bad credentials (HTTP 401)` / `Command failed
(1): gh`, ending the job before any Noema verdict was prepared or published. The job log
timeline (all UTC):

- `15:16:03Z` — the "Mint repository-scoped Noema GitHub App token" step (`noema-review.yml`)
  mints the `cwl-noema-review` installation token via `actions/create-github-app-token`. This
  token has GitHub's fixed ~1 hour TTL; the action has no input to extend it.
- `15:16:05Z`–`15:33:03Z` (~17 min) — "Provision contextual-orchestrator review sidecar" vendors
  and starts the review sidecar and runs health/preflight checks. Its own preflight log shows it
  probed 12 candidate free-tier model routes (`probed_count: 12, rejected_count: 7`), several
  with `TimeoutError` or HTTP 404, before landing on working routes.
- `15:33:07Z`–`16:17:46Z` (~44 min) — "Prepare Noema model verdict" runs
  `.github/actions/noema-review/two_phase.py --prepare-verdict-file`.
- `16:17:46Z` — `gh: Bad credentials (HTTP 401)`, job fails. This is ~61m43s after the `15:16:03Z`
  mint — past the token's ~1 hour TTL.

`.github/actions/noema-review/two_phase.py`'s `prepare_verdict()` runs several fast, early `gh`
calls (`gate.fetch_pr`, `gate.fetch_diff`, `gate.fetch_changed_files`, `gate.build_review_context`)
before ever calling the model, then calls `gate.call_llm()`. That function's own HTTP POST to the
orchestrator sidecar carries no further `gh` calls -- except on its **first-attempt failure path**:
`scripts/ci/noema_review_gate.py`'s `call_llm()`, when the first model attempt raises a recoverable
error (malformed JSON, transport failure) and is not already a retry, calls `fetch_pr(repo, number)`
one more time to confirm the PR head has not moved before firing the one-time, potentially
multi-hour repair-retry request -- avoiding a wasted repair call on a PR that
`inspect_and_review`'s own post-call check would discard anyway. That `fetch_pr()` call is a `gh
api graphql` invocation using whichever `GH_TOKEN` the "Prepare Noema model verdict" step's
environment set -- the same token minted at `15:16:03Z`, never refreshed within the step.

The design that already exists for this exact class of problem -- prepare/publish two-phase
handoff, documented in `docs/doctoring/noema-review-token-lifetime.md` -- re-mints a **fresh** App
token before the separate "Publish prepared Noema verdict" step specifically because model work can
outlive the mint-time token. But that redesign only re-minted for *publication*. It did not account
for `call_llm()`'s own internal repair-retry recheck needing a live credential potentially deep into
the *prepare* phase's own, single, uninterrupted token lifetime -- itself already consuming ~17
minutes of sidecar provisioning plus however long the first (free-tier-routed, occasionally slow)
model attempt takes before failing. When that cumulative time exceeds ~1 hour, the recheck's own
`gh api graphql` call fails with an expired-credential 401 that has nothing to do with the PR's
actual state, and previously crashed the whole job with an unhandled `RuntimeError`.

`.github/workflows/noema-token-lifetime-quality-ci.yml` and its executable contracts
(`test_noema_reviewer_token_lifetime.py`, `test_noema_two_phase_handoff.py`,
`test_noema_refreshed_app_identity.py`) cover the prepare/publish token-remint split; none of them
exercise `call_llm()`'s repair-retry recheck, so this second, narrower token-lifetime gap inside
prepare itself was not caught by that regression suite.

## Fix

`scripts/ci/noema_review_gate.py`'s `call_llm()` now treats a failure of its own repair-retry
live-head recheck the same way it already treats a confirmed-stale head: fail closed, skip the
repair retry, never crash. A new `NoemaRepairRecheckUnavailableError` (a
`StaleHeadDuringRepairRetryError` subclass) is raised when `fetch_pr()` itself raises
(`RuntimeError`, `urllib.error.URLError`, `http.client.HTTPException`, `OSError`, or `ValueError` --
the same failure surface this module's `gh`/JSON-parsing calls can produce), chained from that
recheck failure so the real diagnostic (e.g. `gh: Bad credentials (HTTP 401)`) survives for
operators. Because it subclasses the existing exception, every current caller's bare
`except StaleHeadDuringRepairRetryError` (`prepare_verdict()` in `two_phase.py`,
`inspect_and_review()` in `noema_review_gate.py`) keeps handling it with zero code changes -- both
now exit 0, seal or publish nothing, exactly as if the head genuinely had moved. Both callers were
additionally given a distinguishing `except NoemaRepairRecheckUnavailableError` branch that emits a
`::warning::`-prefixed message including the underlying failure, so this timing failure mode reads
differently from a routine stale-head skip in job logs instead of looking identical to one.

This does not weaken the trust boundary or widen any credential. The repair-retry recheck was
already a pure cost-avoidance optimization ("is a second, possibly multi-hour repair call worth
firing"), never the correctness guarantee itself: `prepare_verdict()` validates the live head via
`require_expected_head()` once at the very start, before any model call, and -- independent of
whatever happened during prepare -- `publish_verdict()` re-fetches the live PR and independently
re-validates the exact head *and* base with a **freshly minted** publication token before ever
submitting review evidence. When this recheck cannot complete, no envelope is sealed, so publication
never runs at all; nothing about the App token's repository scope or minimal permissions changed.

No workflow YAML changes were needed: the fix lives entirely in the trusted, base-branch-owned
Python helpers `pull_request_target` already executes (`scripts/ci/noema_review_gate.py`,
`.github/actions/noema-review/two_phase.py`), which sibling repositories already fetch by exact
commit SHA via the existing `Materialize trusted Noema review gate` step.

## Verification

- `tests/test_noema_review_gate.py::test_call_llm_fails_closed_when_repair_recheck_credential_expires`
  reproduces the exact failure (`fetch_pr` raising `RuntimeError("... gh: Bad credentials (HTTP
  401)")` during the repair-retry recheck) and asserts `call_llm()` raises
  `NoemaRepairRecheckUnavailableError` (a `StaleHeadDuringRepairRetryError`), preserves the
  underlying diagnostic, and fires only the one already-doomed first model request -- never a second,
  wasted one.
- `tests/test_noema_review_gate.py::test_inspect_and_review_reports_repair_recheck_unavailable_as_warning`
  and `tests/test_noema_two_phase_handoff.py::test_prepare_reports_repair_recheck_unavailable_distinctly`
  prove both call sites exit cleanly (return 0, no publish, no sealed envelope) with a `::warning::`
  message distinct from the plain stale-head skip text.
- Full suite: `coverage run -m pytest tests` -- 2584 passed, 1 skipped; `coverage report
  --show-missing` -- 100% statement and branch coverage on `scripts/ci/` (`noema_review_gate.py`
  included); `interrogate` -- 100% docstring coverage. `python3 -m compileall` and `git diff --check`
  clean on every changed file.
- Downstream replay: after this lands on `main`, the next Required Noema Review run whose first
  model attempt is malformed or transport-fails and whose reviewer credential has since expired must
  finish with a clean, typed "verdict not sealed" skip (`::warning::` in the job log), never an
  unhandled `gh: Bad credentials (HTTP 401)` crash.
