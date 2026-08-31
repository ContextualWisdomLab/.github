# Changelog

All notable changes to the organization automation repository are documented in
this file. The format follows Keep a Changelog, and versioned releases follow
Semantic Versioning where the repository publishes a release.

## [Unreleased]
- Fix a dangling reference #1468 left in `docs/product-goal-directive.md`
  (flagged by Devin Review on that PR): the standing operating directive
  still named the removed `free_family_diversity` evidence field instead of
  its `free_account_diversity` replacement, which could send future
  monitoring work looking for a field that no longer exists.
- `scripts/ci/contextual_orchestrator_review_policy.py`'s catalog admission
  cap and diversity evidence no longer conflate "independent credential
  account" with "independent outage domain": `nvidia_nim`/`nvidia_nim_sub`
  are independent accounts (may expose different models) but share one
  physical upstream endpoint (`https://integrate.api.nvidia.com/v1`), so
  they now share one admission-cap budget and count as one outage domain. A
  new `free_outage_domain_diversity` report field (additive, alongside the
  existing `free_account_diversity`) reflects this for callers deciding
  whether a single provider outage could empty the free catalog.
- Noema, Strix, and OpenCode review sidecars now vendor contextual-orchestrator
  at `c107e3e52371993aa9c326fcc245e01c41fc3850` and treat every KV credential
  as an independent discovery account. Same-vendor credentials no longer
  collapse into a provider family; only explicit model groups may share
  routing evidence.
- Web verification now runs backend, frontend, and E2E commands inside an
  isolated Linux bubblewrap workspace by default (`--isolation required`),
  mounting a read-only runtime root with a single writable `/workspace`
  bind; trusted local debugging may opt out with `--isolation disabled`.
  Isolation-backend resolution and the existing loopback readiness-URL
  boundary are now both checked before any service starts, so an
  unavailable isolation backend or an invalid readiness URL fails closed
  with a clear diagnostic (exit code 126/125) instead of after services are
  already running.
- Close four gaps a Devin Review pass found in the same web E2E isolation
  helper (`scripts/ci/sandboxed_web_e2e.py`, `scripts/ci/sandboxed_verify.py`):
  a non-numeric or out-of-range readiness-URL port now raises the same
  `ValueError` every other readiness check raises, instead of an uncaught
  `http.client.InvalidURL` escaping past `main`'s exit-125 handling; a `bwrap`
  binary on `PATH` now passes a bounded capability preflight (proving it can
  actually create the sandbox's namespaces) before isolation is trusted as
  available, so a restricted host fails closed with exit 126 instead of a
  later, confusing readiness/test failure; an executable that cannot be
  resolved on `PATH` is now a hard `isolated_command` failure rather than a
  silent fallthrough that ran unwrapped and unvalidated; and the shared
  workspace copy now rejects (fails the whole copy closed) any symlink whose
  resolved target lands outside the copied tree, since `copytree(...,
  symlinks=True)` otherwise preserves an escaping symlink as a live link
  inside the bind-mounted `/workspace`.
- (Devin review 반영, 후속 라운드) 같은 sandboxed web E2E isolation 헬퍼에 두 건을 추가로
  hardening했습니다: (1) `_probe_isolation_capability`가 이제 `isolated_command`가 실제로
  수행하는 모든 연산(`--new-session`, `/tmp` tmpfs, 실제 명령이 사용하는 것과 동일한 mount
  point로의 쓰기 가능한 bind+chdir)을 진짜 임시 디렉터리로 그대로 재현합니다 — 이전의 축소된
  probe는 이 중 하나를 거부하는 host에서는 통과했다가 실제 서비스 실행에서만 실패할 수
  있었습니다. (2) `scripts/ci/sandboxed_verify.py`의 `copy_workspace` 기본 제외 목록에
  자격증명 관련 dotfile/디렉터리(`.env*`, `.netrc`, `.npmrc`, `.pypirc`, `.pgpass`,
  `.git-credentials`, `.ssh`, `.gnupg`, `.aws`, `.kube`, `.docker`)를 추가했습니다 — 쓰기
  가능한 `/workspace` mount는 테스트 대상 명령이 읽고 쓸 수 있으므로, repo checkout에 우연히
  존재하는 자격증명 파일이 그대로 복사되어서는 안 됩니다(로그·per-command home은 명령이 실제로
  써야 하므로 의도적으로 동일 mount 안에 유지).
- Fix two live-on-`main` regressions Devin Review found immediately after
  PRs #1456 and #1459 merged (both bypass-merged past the org-wide
  `opencode-review` outage; these hotfixes correct real defects the local
  test suites' mocks couldn't catch):
  - `pr_review_fix_scheduler.py`'s `issue_comments()` (#1459) added
    `-f per_page=100` to its `gh api` call without an explicit `-X GET`.
    `gh api` defaults to POST once any `-f`/`-F` field is present unless
    `-X`/`--method` overrides it, so every comment fetch became a malformed
    POST against the comment-*creation* endpoint (no `body` field) --
    failing every call outright and deferring every candidate PR, the
    opposite of this fix's purpose. Now pins `-X GET` explicitly. Added a
    regression asserting the exact argv shape.
  - `pr_review_merge_scheduler.py`'s `rest_pr_node()` (#1456) fetched
    classic commit statuses from `commits/{sha}/statuses` (plural), which
    returns full status history in reverse-chronological order with no
    dedup -- a context that transitioned from success to failure surfaced
    both entries, letting a stale success outlive a later real failure for
    `strix_evidence_state()` (which accepts the first success it finds).
    Switched to `commits/{sha}/status` (singular, combined), which already
    reports only the most recent status per context, matching the GraphQL
    rollup's own shape. Added a regression proving a failed-then-superseded
    context reports `"failed"`, not a stale `"complete"`.
- Root-cause the hourly PR-review-fix scheduler's silent `autofix_dispatches: 0`
  on nearly every run (surfaced while investigating why 40 of `.github`'s 81
  open PRs were stuck reporting "This branch has conflicts that must be
  resolved"): `github-hourly-review-repair.yml`'s most recent run inspected
  50 PRs and dispatched zero autofixes, with every candidate PR's decision
  reading `"error": "API rate limit exceeded for installation ID ..."`. Two
  compounding causes in `scripts/ci/pr_review_fix_scheduler.py`: (1)
  `issue_comments()` fetched a PR's *entire* issue-comment history with the
  default 30-per-page pagination even though `recent_fix_marker_exists()`
  only ever needs the most recent marker; (2) `process_queue()`'s concurrent
  comment-prefetch (up to 10 simultaneous `gh api --paginate` calls against
  the same shared, org-wide-contended OpenCode app installation) silently
  swallowed a failed fetch and then had `inspect_pr()` immediately retry the
  *same* doomed call sequentially with zero backoff, doubling the wasted
  request volume for every already-failing PR. `issue_comments()` now
  requests `per_page=100` (cutting page count for long comment threads by
  up to 3x) and retries a detected rate-limit error with a short linear
  backoff (up to 2 attempts) before propagating; `process_queue()` now
  caps prefetch concurrency at 4 workers instead of 10, and a PR whose
  comment fetch still fails after retries is deferred to the next scheduled
  pass (`"wait"`) instead of silently prefetch-swallowed and then
  redundantly re-fetched and reported as a scary `"error"`. This is a
  single shared script, so the fix applies identically to every one of the
  ~19 product-specific hourly review-repair callers, not just `.github`'s
  own.
- Fix a Devin Review finding on PR #1456: the REST fallback path
  (`rest_pr_node`, used when GraphQL is unavailable) only ever fetched a
  head commit's CheckRuns (`commits/{sha}/check-runs`), never its classic
  commit statuses (`commits/{sha}/statuses`), so a same-head manual
  `workflow_dispatch` Strix run's classic-status evidence silently
  disappeared under REST fallback -- `strix_evidence_state()` would see no
  Strix evidence at all and could never reach `"complete"` through that
  identity, exactly the loss of manual evidence the two preceding fixes on
  this PR were built to preserve. `rest_pr_node` now also fetches classic
  statuses and folds them into the same `statusCheckRollup.contexts.nodes`
  list via a new `rest_status_node` shape converter, alongside the existing
  CheckRun conversion. Added a regression assertion that a classic status
  survives the REST fallback and that `strix_evidence_state()` sees it as
  `"complete"` end-to-end.
- Fix a second, immediately-following Devin Review finding on PR #1456
  (`strix_evidence_state()`), which directly refined the previous entry's
  fix: making a required-workflow CheckRun the sole authority whenever
  present also meant a genuinely failing CheckRun could never be excused by
  a same-head manual `workflow_dispatch` Strix run's classic-status
  success -- but this repo documents exactly that as intended: a manual run
  "may supply review evidence but does not replace required PR checks",
  precisely for a self-modifying `.github` PR whose `pull_request_target`
  CheckRun runs the *base* branch's trusted scripts and can legitimately
  fail against a PR editing those very scripts, while a trusted same-head
  manual dispatch correctly evaluates the new code. `strix_evidence_state()`
  now treats either Strix identity's authoritative success as sufficient
  for "complete" (never substituting for GitHub's own independently
  enforced required CheckRun at actual merge time, which this function does
  not touch); only when *no* identity ever succeeds does it report "failed".
  This still resolves the original endless-rerun-loop defect (a stale
  classic failure can no longer block a since-succeeded CheckRun) while
  also letting a genuine same-head manual success unblock review when the
  CheckRun itself is the one that's wrong. Updated the previous round's
  regression test asserting the reverse case as "failed" to the corrected
  "complete", and added a fourth case (both identities failing, still
  correctly "failed") to keep every combination covered.
- Fix a Devin Review finding on PR #1456: `strix_evidence_state()` treated a
  classic commit-status Strix context (e.g. a same-head manual
  `workflow_dispatch` run) as equally authoritative to a required-workflow
  Strix CheckRun, so a stale classic-status failure left the gate "failed"
  forever even after the real CheckRun evidence succeeded --
  `dispatch_strix_evidence()` can only rerun a CheckRun's Actions job, never
  a classic status, so this produced an endless, pointless rerun loop that
  permanently blocked OpenCode dispatch. A required-workflow CheckRun is now
  the sole authority whenever one is present; a classic status is evaluated
  only when no CheckRun exists at all, matching this repo's documented
  policy that a manual run "may supply review evidence but does not replace
  required PR checks." Added regression tests for a stale classic failure
  beside a successful CheckRun (now "complete"), a genuinely failing
  CheckRun beside an unrelated classic success (still correctly "failed"),
  and a still-running CheckRun beside a stale classic failure (still
  "running", not prematurely "failed").
- Let an explicit mention-triggered review request (`@opencode-agent review`)
  actually dispatch a current-head OpenCode review for a **draft** PR.
  `pr_review_merge_scheduler.py`'s `inspect_pr()` unconditionally returned
  `skip: draft PR` before reaching any review-dispatch logic, so
  `agent-mention-opencode-dispatch.yml`'s already-structurally-review-only
  forward to the scheduler (`trigger_reviews=true`, `enable_auto_merge=false`,
  `update_branches=false`, `merge_mode=disabled`) was silently discarded for
  drafts: the mention router resolved and forwarded the request correctly,
  but the scheduler never posted a review. New opt-in `--allow-draft-review-dispatch`
  CLI flag (requires `--pr-number`; rejected otherwise) and `inspect_pr()`
  parameter route a draft PR through a new `dispatch_draft_review_only()`
  helper that runs the same Strix-then-OpenCode dispatch gate the ready-PR
  pipeline uses, then returns immediately — before any of `inspect_pr`'s
  unresolved-thread, changes-requested, branch-update, or auto-merge logic,
  so a draft still cannot be merged, auto-merged, or have its branch updated
  through this path. `pr-review-merge-scheduler.yml`'s `scan-pr-queue` job
  sets the new `ALLOW_DRAFT_REVIEW_DISPATCH` flag from
  `github.event.client_payload.agent_invocation_key` — a field only the
  mention-dispatch workflow ever sets — so the ordinary multi-PR queue sweep
  (schedule/push/pull_request_target/pull_request_review/workflow_run) keeps
  skipping drafts exactly as before.
  Three follow-up fixes from adversarial review before this shipped:
  - `dispatch_draft_review_only()` treated `opencode_progress_state(pr) == "complete"`
    (a matching check/status reached a terminal state) as proof a verdict
    exists. That state does not distinguish a posted review from the
    required-workflow gate's own terminal failure when no verdict was ever
    dispatched, so a failed dispatch attempt would permanently block every
    later explicit retry. Now gated on an actual current-head formal review
    (`has_current_head_approval`/`has_current_head_changes_requested`),
    matching the non-draft path's own review-state checks.
  - When Strix evidence is missing, the initial mention dispatches Strix and
    ends that scheduler run; the Strix-completion `workflow_run` that follows
    carries no `repository_dispatch` `client_payload` of its own, so the
    first design's env-var-driven flag would be unset on that later pass and
    the draft would fall back to being skipped before ever reaching OpenCode.
    `agent-mention-opencode-dispatch.yml` now claims a short-lived
    (`retention-days: 1`), exact-head-named Actions artifact
    (`cwl-draft-review-request-<repo>-<pr>-<head-sha>`) alongside its existing
    invocation ledger, only after its own HMAC-style canonical-payload check
    has already validated the invocation; `inspect_pr()`'s draft branch
    checks for this durable marker (`active_draft_review_request()`), so a
    later pass over the same exact head — the ordinary `workflow_run`
    trigger, single-PR or the bulk sweep — still recognizes and continues
    the same explicit request through to OpenCode dispatch.
  - The first design's `ALLOW_DRAFT_REVIEW_DISPATCH` env var trusted the mere
    *presence* of `client_payload.agent_invocation_key` on a `merge-scheduler`
    `repository_dispatch` event as proof of a legitimate mention, without
    verifying the key or binding it to a specific head. Any dispatch-capable
    caller could supply an arbitrary nonempty string for an arbitrary target
    repository/PR to get an unrequested draft review dispatched, and a
    genuinely stale mention (new commits landed after the request) would
    review a commit nobody asked about. Removed that env var and its CLI
    pass-through entirely — `active_draft_review_request()`'s cryptographically
    gated, exact-head-named artifact marker (above) is now the sole automatic
    gate; `--allow-draft-review-dispatch` remains only as a manual,
    direct-CLI operator override.
  - `strix_evidence_state()` classified *any* terminal Strix check-run or
    commit-status as `"complete"` because it only ever inspected `status`
    (CheckRun) / whether a value was present (classic status) to tell
    running from terminal, never the actual `conclusion` (CheckRun) or
    terminal `state` value (classic status). A terminal `FAILURE`, `ERROR`,
    `CANCELLED`, `TIMED_OUT`, `SKIPPED`, `NEUTRAL`, `ACTION_REQUIRED`,
    `STALE`, or `STARTUP_FAILURE` outcome therefore satisfied the same gate
    as an authoritative `SUCCESS`, letting non-passing Strix evidence unlock
    OpenCode dispatch on both the draft review-only path and the ordinary
    scheduler path. The function now returns a new `"failed"` state whenever
    Strix evidence is terminal but not an authoritative success, and every
    call site (`post_update_branch_followup`, `dispatch_draft_review_only`,
    and the main non-draft `inspect_pr` Strix-then-OpenCode chain) treats
    `"failed"` exactly like `"missing"`: it dispatches a fresh Strix attempt
    and never falls through to OpenCode on that non-authoritative evidence.
    Fails closed by design: any single non-success terminal context marks
    the whole gate `"failed"` even alongside a successful one. Added
    exhaustive regression fixtures for every non-passing terminal
    conclusion/state plus authoritative success, for both CheckRun and
    classic commit-status shapes.
  - Two more adversarial-review findings against that same fix, both fixed:
    - `strix_evidence_state()` walked every Strix context node in the
      rollup directly, so a rerun's stale failed CheckRun attempt (GitHub
      keeps every prior attempt's CheckRun node alongside the latest one)
      could permanently keep the gate `"failed"` even after a later retry
      succeeded. Extracted the CheckRun-identity dedup `failed_status_checks()`
      already used (latest attempt per `(workflow, name)`, by `startedAt`
      then rollup order) into a shared `latest_check_run_attempts()` helper
      and evaluate only the latest attempt per Strix CheckRun identity.
      `failed_status_checks()` itself now calls the same helper instead of
      duplicating the dedup logic, with no behavior change. Added
      regression tests for an older failed attempt followed by a newer
      success, the reverse ordering, and a running retry after a failure.
    - `active_draft_review_request()`'s Actions-artifact read used the
      generic target-repository read credential
      (`gh_api_json`/`SCHEDULER_READ_TOKEN`), but the artifact always lives
      in the central `.github` repository regardless of which repository
      the PR belongs to, and — per `scheduler_dispatch_env()`'s own
      pre-existing documented fact — "the OpenCode app installation has no
      Actions permission." For a cross-repository dispatch with only the
      OpenCode app credential configured (no `PR_REVIEW_MERGE_TOKEN`/
      `OPENCODE_APPROVE_TOKEN` secret), the read credential resolved to
      that same Actions-permission-less app token, so the artifact read
      would fail and the initial mention-triggered request for a draft PR
      outside `.github` could never get past its own authorization check.
      New `gh_api_json_via_dispatch_token()` reads through
      `run_github_dispatch()`/`SCHEDULER_DISPATCH_TOKEN` instead — the same
      central-repository dispatch credential already used to create the
      `repository_dispatch` there — which the workflow always sets to the
      runner's own `github.token`, valid for `.github`'s own Actions
      artifacts regardless of the PR's actual repository. Added a
      regression test proving the read uses the dispatch token, not
      whatever generic `GH_TOKEN` the OpenCode app credential resolves to.
  - One more adversarial-review finding against that same dispatch-token
    fix: the central-repository dispatch credential is itself only valid
    when this scheduler executes inside `.github`. `scan-pr-queue` has no
    such guard — the organization's required-workflow ruleset runs it
    directly in each sibling repository's own context for that repository's
    ordinary (non-mention) PR events, where `github.token` is scoped only
    to that sibling repository and cannot read `.github`'s artifacts
    either. `active_draft_review_request()` previously let that `gh`
    failure -- or a malformed/tampered artifact-list response -- propagate
    as an unhandled exception, replacing the intended `skip: draft PR`
    outcome with an error that would abort the whole multi-PR scan over one
    draft PR. It now resolves any such failure to `False` (no confirmed
    active request) instead, the same safe outcome as a completed check
    that finds nothing. Added regression tests for both the credential
    failure and a malformed response.
- Fix one more Devin Review finding on PR #1452, a genuine gap in the round-4
  malformed-gateway-reply fix (`scripts/ci/contextual_orchestrator_review_sidecar.sh`,
  `tests/test_contextual_orchestrator_review_runtime_preflight.py`):
  `json.loads()` legally parses a top-level JSON array, `null`, a bare
  string, or a number, not just an object -- the immediately following
  `response.get("choices")` assumes a dict and raises `AttributeError` for
  any of those, which was not in the round-4 fix's caught exception tuple,
  so a valid-JSON-but-wrong-shaped HTTP 200 body still lost evidence exactly
  like the original bug (the script still failed closed overall, since an
  uncaught exception exits non-zero, but wrote nothing to the gateway
  evidence report). Fixed with an explicit `isinstance(response, dict)`
  check that raises the already-caught `TypeError` rather than widening the
  tuple to `AttributeError` broadly. Added parametrized regression tests
  (`[]`, `null`, a bare string, and a bare number) confirmed to fail against
  the pre-fix script before the fix, and pass after. 1930 tests pass; 100%
  coverage and 100% docstring coverage on `scripts/ci/`.
- Fix 3 more Devin Review findings from a fourth review pass on PR #1452
  (`scripts/ci/contextual_orchestrator_review_launcher.py`,
  `scripts/ci/contextual_orchestrator_review_sidecar.sh`,
  `tests/test_contextual_orchestrator_review_runtime_preflight.py`), plus two
  doc/test-staleness cleanups: an escalated attempt's EXCEPTION handler
  (`_record_provider_exception`) left the base attempt's stale
  `finish_reason`/`reasoning_without_content` on the row -- the same
  mixed-attempt-telemetry bug class already fixed for the escalated-empty
  and escalated-success outcomes, now closed for the escalated-exception
  outcome too (both fields are cleared, not backfilled, since there is no
  response object to describe). `_response_has_reasoning_without_content`
  checked only whether `message.reasoning` was truthy, never whether
  `message.content` was actually empty/absent -- so a normal, complete
  answer that also discloses a reasoning trace alongside real content would
  be wrongly flagged as "starved" (this had gone latent-but-harmless while
  the predicate was only ever called on already-known-empty responses; the
  round-3 fix that started calling it on the SUCCESS path exposed the
  actual bug for the first time). Fixed to require content be genuinely
  absent, reusing `_chat_response_has_text`'s own definition so the two
  predicates are provably consistent; same predicate fixed in the sidecar
  script's mirrored Layer 2 logic. A malformed/unparseable HTTP-200 gateway
  response body (or a missing response file) hit the bare
  `except (...): pass` fallback and wrote nothing to the gateway evidence
  report -- the same evidence-loss pattern as the earlier transport-
  exhaustion fix, a different trigger -- now records a bounded
  `gateway_invalid_response` classification via the same atomic-write
  pattern. Extended the fake-curl harness with `NOFILE:<status>` and
  malformed-JSON-body plan entries to cover both. Also corrected a stale
  test docstring (still described the routing probe as proving every route
  at the real 4096-token budget, no longer true since most routes now prove
  readiness at the cheaper 16-token base probe) and updated ADR-0005's
  status from `proposed` to `accepted` with its Consequences section
  reframed to present tense, now that this PR implements it. 1926 tests
  pass; 100% coverage and 100% docstring coverage on `scripts/ci/`.
- Fix 2 more Devin Review findings from a third review pass on PR #1452
  (`scripts/ci/contextual_orchestrator_review_launcher.py`,
  `scripts/ci/contextual_orchestrator_review_sidecar.sh`,
  `docs/adr/0005-sidecar-preflight-token-budget.md`,
  `tests/test_contextual_orchestrator_review_runtime_preflight.py`): an
  escalated-attempt HTTP rejection (401 auth, 429 throttle, 5xx server error)
  was unconditionally labeled `escalated_probe_rejected`, wrongly implying
  every one of those was evidence the token budget specifically was too large
  -- no status code alone is that evidence, and this codebase deliberately
  never captures raw provider error text that could validate the distinction.
  Extracted a shared `_record_provider_exception` helper so the escalated
  attempt now gets the exact same sanitized exception-type/HTTP-status
  classification the base probe already used, with parametrized 401/429/5xx
  test coverage; the ADR's own text (which originally claimed this
  attribution) is corrected in place. Separately, `finish_reason`/
  `reasoning_without_content` were only ever populated on failure/escalation
  outcomes, never on an ordinary successful probe (the most common case) --
  now populated on every outcome, in both the launcher and the sidecar
  script's successful-gateway-evidence writer, so future tuning has a real
  "normal" baseline to compare against. 1920 tests pass; 100% coverage and
  100% docstring coverage on `scripts/ci/`.
- Fix 3 more Devin Review findings from a second review pass on PR #1452
  (`scripts/ci/contextual_orchestrator_review_launcher.py`,
  `scripts/ci/contextual_orchestrator_review_sidecar.sh`,
  `tests/test_contextual_orchestrator_review_runtime_preflight.py`), triggered
  by the push that resolved the first 7: a successful escalated attempt still
  carried the base attempt's stale `finish_reason`/`reasoning_without_content`
  (the same class of bug as the mixed-attempt fix above, on the opposite
  branch) -- now both fields are refreshed from the escalated response on
  success too. `REVIEW_PREFLIGHT_GATEWAY_MAX_ATTEMPTS`'s new `case` guard
  rejected non-numeric values but not oversized all-digit ones, which hit the
  identical `[ -ge ]` integer-overflow failure mode the guard exists to
  prevent (reproduced directly: a 55-digit value fails the same way a
  non-numeric one did) -- the guard now also caps digit count (at most 4
  digits, 9999). Added mixed-outcome fake-curl tests (transport failure then
  HTTP rejection, and the reverse) proving exhaustion evidence reflects
  whichever attempt actually happened last. Two further findings from the same
  pass -- (1) a base-probe success never confirms the candidate at the real
  serving token budget (only escalation-on-failure does), and (2)
  `discover_all_models()`'s own up-to-~105s sequential network time (verified
  against the vendored `contextual_orchestrator.model_discovery` source: ~7
  sequential HTTP calls at up to 15s each) is not counted against the same
  180s watchdog Layer 1's 160s probing bound assumes it has entirely to
  itself -- are real, verified, and architecturally significant enough to need
  their own design pass rather than a guessed patch; documented in place with
  cross-references and tracked as `ContextualWisdomLab/.github#1454` and
  `#1455` respectively, left open (not resolved) on the PR. 1917 tests pass;
  100% coverage and 100% docstring coverage on `scripts/ci/`.
- Fix 7 Devin Review findings on PR #1452, ADR-0005's implementation
  (`scripts/ci/contextual_orchestrator_review_launcher.py`,
  `scripts/ci/contextual_orchestrator_review_sidecar.sh`,
  `tests/test_contextual_orchestrator_review_runtime_preflight.py`). Two were
  blocking: (1) `_preflight_review_agents` reset its escalation counter fresh
  on every call, so `_preflight_with_fallback` calling it twice (primary,
  then fallback) could spend the full `REVIEW_PREFLIGHT_MAX_ESCALATIONS`
  budget in each stage -- up to 200s, past Layer 1's 180s
  healthz-readiness watchdog and contradicting the ADR's own claimed 160s
  worst case. Fixed by threading the primary stage's ending
  `escalations_used` into the fallback stage as its starting point, so one
  shared budget covers the whole run; both stages' counts remain visible in
  the returned evidence. (2) A non-numeric, empty, zero, or negative
  `REVIEW_PREFLIGHT_GATEWAY_MAX_ATTEMPTS` made the shell script's integer
  comparison silently fail on every iteration, removing the retry bound
  entirely instead of failing closed. Fixed with an explicit `case` guard
  before the retry loop starts. The remaining five: an escalated-attempt
  transport failure (no HTTP status at all) was mislabeled
  `EscalatedProbeRejected`, falsely attributing a connectivity failure to
  the token budget -- now distinguishes on HTTP-status presence, falling
  back to the sanitized exception type otherwise; total transport-attempt
  exhaustion at Layer 2 used to `fail` without ever writing gateway evidence
  -- now records a bounded `gateway_transport_exhausted` classification
  first, via the same sanitize-and-atomic-replace pattern the non-2xx and
  invalid-content paths already use; Layer 1's error-type strings were
  CamelCase (`EscalatedProbeRejected`, `InvalidChatResponse`,
  `EscalationBudgetExhausted`) while the ADR and Layer 2 already used
  snake_case -- Layer 1 (and Layer 2's one remaining outlier) now match:
  `escalated_probe_rejected`, `invalid_chat_response`,
  `escalation_budget_exhausted`, `gateway_transport_exhausted`; the Layer 2
  gateway retry-loop test only asserted source literals rather than
  executing the loop -- added a fake-curl harness (extracting the tracked
  script's real retry-loop source and running it under `bash` against a
  scripted, no-network `curl` stand-in) covering first-attempt success,
  transport-failure recovery, non-2xx exhaustion, transport exhaustion, and
  the malformed-attempt-limit guard; and a mixed-attempt telemetry bug where
  `finish_reason` reflected the escalated attempt while
  `reasoning_without_content` was left describing the base attempt -- both
  fields now always describe the same (most recent) attempt. 1913 tests
  pass; 100% coverage and 100% docstring coverage on `scripts/ci/`.
- Implement ADR-0005's diagnostic, bounded-retry sidecar preflight
  (`scripts/ci/contextual_orchestrator_review_launcher.py`,
  `scripts/ci/contextual_orchestrator_review_sidecar.sh`). A 5th Devin
  Review pass on the ADR found the escalation predicate
  (`finish_reason == "length"` alone) missed the vendored
  `ModelClient._response_content`'s own broader "reasoning without
  content" signature -- the exact original PR #1436 failure mode --
  verified directly against current orchestrator.py before fixing.
  Layer 1's per-candidate probe now starts at a new
  `REVIEW_PREFLIGHT_BASE_TOKENS = 16` and escalates the same candidate
  once to the existing `REVIEW_MAX_OUTPUT_TOKENS` (4096) only when the
  response is empty and either `finish_reason == "length"` or a
  populated `reasoning` field is present, bounded by a shared
  `REVIEW_PREFLIGHT_MAX_ESCALATIONS = 4` across the whole run. Layer 2
  keeps its existing 4096/120s budget unchanged and retries only on
  transport failure/non-2xx, up to
  `REVIEW_PREFLIGHT_GATEWAY_MAX_ATTEMPTS = 3`, labeling a
  retry-specific rejection `gateway_retry_rejected` rather than
  implying candidate-ceiling attribution it cannot support. 1901 tests
  pass; 100% coverage and 100% docstring coverage on `scripts/ci/`.
- Add `docs/adr/0005-sidecar-preflight-token-budget.md`, an evidence-based
  design decision responding to the owner's direct critique that a single
  hardcoded `max_tokens` cannot fit a heterogeneous `orchestrator/free` pool.
  Revised after six verified Devin Review findings on its PR (#1449),
  including two real design flaws in the first draft: reusing a fixed tiny
  `max_tokens` for a per-candidate probe reproduces the same
  reasoning-budget-starvation bug one layer down, and dropping the sidecar's
  separate virtual-pool smoke request in favor of per-candidate checks alone
  cannot catch a virtual-pool dispatch bug (already documented live on
  PR #1433). The current decision keeps both existing preflight layers
  (`_preflight_review_agents`/`_preflight_with_fallback` in the launcher; the
  shell script's virtual-pool request). A second Devin Review pass then found
  the first revision's single retry predicate could not fire for the exact
  live evidence cited (a `curl` timeout with zero bytes has no `finish_reason`
  to inspect), plus an unbounded-looking worst case and other gaps. Revised
  again to model two distinct, explicitly-bounded retry triggers: no-response
  (timeout/connection failure) retries at the same budget; a response with
  `finish_reason == "length"` escalates the budget. Layer 2's existing,
  already-evidenced 120s per-attempt timeout is kept unchanged (shortening it
  would regress this file's own prior 30s→120s fix) and gets up to 3 bounded
  attempts instead of one with no recovery path; Layer 1 stays within its
  existing 180s ceiling via a computed, capped escalation budget. Adds two
  real tracked upstream issues (`ContextualWisdomLab/contextual-orchestrator#926`,
  `#927`) and SHA-pinned permalink citations (`8b3235d2...`) in place of both
  prose-only follow-ups and line numbers that would otherwise rot. A third
  Devin Review pass found the revised text still self-contradicted which
  layer retries on which trigger, plus an attribution problem: Layer 2's
  escalation retried the virtual pool, not a pinned candidate, so a
  rejection there could not be honestly blamed on one candidate's ceiling.
  A fourth pass found a sharper version of the same question -- a
  `finish_reason == "length"` response is still HTTP 200, so the gateway's
  routing already recorded that attempt as successful, making a same-budget
  retry more likely to repeat the same candidate than diversify away from
  it. Per this org's convergence rule, and after directly checking
  `contextual_orchestrator/server.py` for a candidate-exclusion parameter
  and finding none: Layer 2 no longer retries on `finish_reason == "length"`
  at all, only on transport failure/hang, and its route diversity is stated
  as an unverified best effort rather than a guarantee. Layer 1 (which pins
  one specific candidate per attempt) is unaffected. Consequences corrected
  from present tense to prospective, matching the ADR's `proposed` status.
  A fifth Devin Review pass found Trigger B's definition itself was too
  narrow: `finish_reason == "length"` alone misses the vendored
  `ModelClient._response_content`'s own broader "reasoning, no content"
  signature (a populated `message.reasoning` field with no string
  `content`, already anticipated in the codebase's own error message) --
  exactly the original PR #1436 failure mode, since a reasoning model can
  exhaust its budget under a different or absent `finish_reason`, and
  provider `finish_reason` semantics for this case aren't verified as
  uniform across a pool this heterogeneous. Trigger B is now defined as
  `finish_reason == "length"` OR that reasoning-without-content signature,
  consistently through Decision §1 and §3 and the "every other outcome"
  fallback case; Layer 2's "no retry on Trigger B" applies to both halves
  of the signature, not just the finish_reason one. A sixth Devin Review
  pass (two findings, verified against the vendored source directly) found
  two more precision/scope gaps. First: `_response_content` checks
  `isinstance(content, str)` before ever inspecting `reasoning`, so a
  genuinely empty string `""` (not missing/`null`) is treated as a valid,
  non-erroring return and never reaches the reasoning-without-content
  check -- the already-implemented preflight predicate in `ContextualWisdomLab/.github#1452`
  was independently verified to already handle this correctly (it treats
  `content == ""` the same as missing content, deliberately broader than
  `_response_content`'s own narrower technical condition), so this was a
  documentation-precision gap, not a code bug; the ADR's Trigger B
  definition and a new precision note now state explicitly that this
  preflight's "no usable content" is broader than any one downstream
  library call's exact return-value convention. Second: a
  reasoning-without-content failure at Layer 2 can itself surface as a
  generic `HTTP 502` (`server.py`'s blanket `except ProviderResponseError:`
  handler collapses both `ProviderResponseError` causes into an identical
  body with no distinguishing field), so it is misclassified as Trigger A
  and retried up to 3 times instead of failing fast as Trigger B --
  verified as requiring an out-of-scope `contextual-orchestrator` change to
  fix properly (no in-repo workaround exists that avoids fragile
  message-text matching), so documented as a known, accepted, tracked
  Layer 2 limitation (`ContextualWisdomLab/contextual-orchestrator#932`,
  following the `#926`/`#927` pattern) rather than worked around. No code
  change in this PR; the sidecar migration is tracked separately. A seventh
  Devin Review pass found four more items, judged against this org's
  convergence rule after 26+ review threads across seven rounds on this
  docs-only PR. Trivial: the Evidence trail's upstream-issue citation still
  named only `#926`/`#927`, missing `#932` -- added. Cross-reference gap,
  not a new architectural question: Layer 1's `160s` worst case (Decision
  §3) still didn't reference `ContextualWisdomLab/.github#1455` (the
  discovery-timing gap filed and fully reasoned during the implementation
  pass) anywhere in this ADR's own text -- added the cross-reference at the
  point of definition and in Consequences, without reopening the
  underlying question #1455 already tracks. Genuinely new, verified real:
  the shared, catalog-order-consumed `REVIEW_PREFLIGHT_MAX_ESCALATIONS`
  budget can deny a later-sorting, healthy candidate its own escalation
  attempt once 4 earlier candidates have claimed the budget -- catalog
  order is deterministic, not random, but not purely alphabetical either:
  `build_zdr_prioritized_catalog` sorts by `(cost_evidence_rank,
  zdr_attested_rank, provider, model)`, so alphabetical `(provider, model)`
  is only the tie-breaker within each same-cost/same-ZDR-status group.
  Considered reordering (round-robin, random shuffling) as a cheap fix and
  rejected it: no selection policy for a fixed-size shared budget removes
  the underlying trade-off, only changes which arbitrary policy governs
  it, and picking one without real evidence would itself be the kind of
  unjustified heuristic this ADR already rejects elsewhere. Documented as
  a known, accepted, tracked limitation (`ContextualWisdomLab/.github#1458`,
  matching the `#1454`/`#1455`/`#932` pattern) rather than redesigned.
  Informational, no change: the gap-baseline's repeated review-round
  narrative is this repo's own documented, intentional convention
  (ADR-0002: the baseline is "an operational snapshot," not a duplicate of
  the ADR's design record), not accidental redundancy.- Raise `contextual_orchestrator_review_sidecar.sh`'s
  `ORCHESTRATOR_CATALOG_FAMILY_CAP` default from 4 to 8: root-caused the
  live "no provider route passed the Strix plain-chat preflight" outage
  blocking `noema-review`/`opencode-review`/`strix` org-wide to
  `contextual_orchestrator_review_policy.py`'s family-cap candidate
  selection deterministically admitting the same 4 alphabetically-first
  `nvidia_nim`/`nvidia_nim_sub` free-model candidates on every run — 2 of
  which are confirmed NVIDIA-retired model ids returning HTTP 404 forever —
  while ~19 other healthy free candidates in the same discovery report
  never got a chance. See the 2026-08-30 sidecar-preflight gap-baseline
  entry for the full evidence trail, the exact trade-off reasoned through
  (not live-verified, since this session lacks provider credentials), and
  the more complete fix if this proves insufficient.
- Switch Strix from `orchestrator/auto` to `orchestrator/free`, matching
  OpenCode and Noema: `strix.yml`'s `STRIX_MODEL`/`CONTEXTUAL_ORCHESTRATOR_POOL`
  default and both model-override allowlists, and
  `scripts/ci/strix_quick_gate.sh`'s `is_contextual_orchestrator_model`, now
  accept only `orchestrator/free`. This is an explicit, informed owner
  override of `docs/adr/0003-contextual-orchestrator-vendored-free-zdr.md`'s
  original `orchestrator/auto` decision (see that ADR's 2026-08-30
  amendment and the matching gap-baseline entry for the full trade-off and
  evidence trail): Strix no longer has a paid-model fallback and can go
  fully dark during the class of single-provider-family-collapse incident
  the original decision was written to survive, until the free-catalog's
  stale-model and provider-diversity gaps are separately closed.
- Strengthen `scripts/ci/zdr_policy.py`'s `nvidia_nim`/`nvidia_nim_sub` ZDR
  attestation with a direct primary-source citation: NVIDIA's own current
  *NVIDIA API Trial Terms of Service* (v. September 19, 2025), Section
  3.3(iv), states User Content and Generated Content are collected "to
  improve NVIDIA products and services, including AI models" — affirmative
  evidence against zero data retention, not just an absence of attestation.
  `zero_data_retention` stays `False` as it already was; only the citation
  and note change. See the 2026-08-30 ZDR/NIM-routing gap-baseline entry for
  the full architecture review this citation was part of.
- Bump the vendored `contextual-orchestrator` review-sidecar pin from
  `5f2753a` (the #1422 pin) to current `main` `30c6d716`, picking up
  `ContextualWisdomLab/contextual-orchestrator#919`: generalizes the
  Models.dev free-cost join beyond `opencode_zen` to `nvidia_nim`/
  `nvidia_nim_sub`/`openai`, and fixes the actual root cause — `_fetch_json`
  sent no `User-Agent`, so Cloudflare-fronted `models.dev` rejected every
  discovery request with HTTP 403, silently breaking the Models.dev join for
  every provider (including the pre-existing `opencode_zen` path). See the
  2026-08-30 gap-baseline entry for the merge/bypass rationale.
- Keep the required OpenCode bootstrap's Pingora policy step unconditional
  within its pull-request-only workflow, so the static bootstrap contract does
  not depend on event payload fields. (Ported from #1414, not yet merged, to
  unblock this PR's own `exact-head-path-policy` check.)
- Bump the vendored `contextual-orchestrator` review-sidecar pin from
  `b2164511` (103 commits stale) to current `main` `5f2753a`, so the
  gateway's model-discovery/ZDR/pool-selection fixes landed since the old pin
  reach `opencode-review`/`noema-review`. The stale pin's discovery logic was
  failing the sidecar's own preflight with a gateway 502 before any review
  could post, which is why `opencode-review` and `noema-review` were failing
  closed on most `contextual-orchestrator` PRs and several `.github` PRs.
- Skip trusted base Python lock materialization for exact-head reviews with no
  Python source or dependency-manifest changes, while preserving the
  fail-closed wheel-only path when Python coverage is relevant.
- Route required Strix scans through the contextual-orchestrator
  `orchestrator/auto` pool so the five configured provider credentials form
  real cross-provider failover. Priced routes require finite, nonnegative
  published prompt/completion prices and an explicit currency; unknown pricing
  fails closed. Private-target ZDR enforcement and the no-external-fallback
  contract remain unchanged.
- Allow the protected Strix required-workflow smoke to recognize only the
  existing `orchestrator/free` route or the provider-diverse
  `orchestrator/auto` route. This provides a fail-closed two-phase migration
  path without admitting direct-provider model identifiers.
- Give stacked pull requests a separately bounded organization-sweep
  OpenCode dispatch budget, so default-branch review traffic cannot leave a
  stacked PR at `OpenCode review absent` without changing the protected merge
  or exact-head evidence rules.
- Add a bounded hourly LineageWeave stacked-PR review-repair caller while
  preserving the existing review-agent, model-routing, and protected-merge
  boundaries. Product-gap development remains a separately gated coordinator
  capability and is not claimed by this caller. The shared repair scheduler
  now treats an explicit `*` base scope as all branch bases so stacked pull
  requests are inspected instead of silently filtered out.
- Ensure the central Security Scan and SAST Semgrep pull-request workflows
  trigger for stacked PRs targeting feature branches, preserving the same
  diff-scoped dependency and repository-wide filesystem security coverage.
- Harden the contextual-orchestrator Strix sidecar by rejecting line-breaking
  bearer tokens and masking the token before clone, install, launch, or health
  diagnostics can emit it. The raw bearer no longer enters `GITHUB_ENV` (where
  a later step header could render it before masking); only a mode-0600 token
  file path crosses steps, and each model consumer validates and masks the file
  inside its own step. The bounded required-workflow smoke now parses every
  governed shell input independently, including the sidecar and token loader.
  Strix also qualifies only the loopback child model as
  `openai/orchestrator/free`, which satisfies LiteLLM's explicit-provider
  contract while preserving `orchestrator/free` at the gateway boundary; a
  missing, empty, or non-pinned contextual-orchestrator API base fails closed.
- Restore OpenCode coverage honesty and mermaid surfaces stacked on main after #1360 squash `17052a7c`: `publish_fallback_diff_review` posts a COMMENT product-file review then `request_changes_for_coverage_evidence_failure` sets the status comment to `COVERAGE_BLOCKED` so a coverage miss never looks finished as `Gate result: COMMENT`; mermaid labels crates/packages instead of generic `Changed file (N files)` and does not invent class edges; findings say `Review process` instead of `.github/workflows/opencode-review.yml:1` unless that file is in the diff. Does not change `noema-review.yml` (PM owns `feat/noema-orchestrator-free-zdr`) and is not NIM-2h or GitHub Models.
- Required OpenCode dispatch and Strix now use the vendored
  `contextual-orchestrator/orchestrator/free` gateway for model execution and
  failed-check diagnosis. The generated OpenCode config contains only the
  gateway provider, Strix rejects non-gateway model overrides and external
  fallbacks, and private-target visibility enables the sidecar's attested ZDR
  requirement. The sidecar installs its vendored dependencies with the
  hash-pinned lock, and gateway provider exhaustion remains fail-closed.
- Required Noema review now routes through the same vendored
  `contextual-orchestrator` sidecar as the autofix writer: `noema-review.yml`
  provisions the gateway with the five provider secrets, points the LLM step
  at the loopback `orchestrator/free` pool (ZDR-first auto-discovery), and
  deletes the public-repo NVIDIA NIM hardcode. `call_llm` keeps SSRF closed
  for arbitrary private and `localhost` targets and allows only the
  orchestrator sidecar loopback (`127.0.0.1` / `::1`) only when it matches the
  exact configured sidecar base URL. Reviewer identity
  is unchanged (`NOEMA_REVIEW_TOKEN` / GitHub App / OIDC; never
  `github.token`). The hourly-review-repair roster is untouched.
- Central review now routes through the vendored `contextual-orchestrator`
  gateway sidecar: the write-capable PR autofix and the shared `opencode.jsonc`
  default use the fail-closed zero-cost pool `orchestrator/free`, with
  ZDR-compliant (zero-data-retention) routes prioritized inside it. The five
  provider secrets (`BYTEZ_API_KEY`, `NVIDIA_NIM_API_KEY`,
  `NVIDIA_NIM_API_KEY_SUB`, `OPENROUTER_API_KEY`, `OPENAI_API_KEY`) are
  registered into the gateway's process-local KV as bootstrap transport, model
  selection is delegated to the orchestrator's auto model discovery, and the
  previous direct NVIDIA NIM pin is gone from the autofix writer. Adds
  `scripts/ci/zdr_policy.py`,
  `scripts/ci/contextual_orchestrator_review_policy.py`,
  `scripts/ci/contextual_orchestrator_review_launcher.py`, and
  `scripts/ci/contextual_orchestrator_review_sidecar.sh` with contract-test and
  ZDR/audit evidence (`docs/adr/0003-contextual-orchestrator-vendored-free-zdr.md`,
  `docs/doctoring/contextual-orchestrator-vendored-sidecar.md`). Mutation
  authority is unchanged: app-token-only, never `github.token`.
- Dependency updates now keep coverage evidence when the lock file passes
  validation. If validation reports a problem, refresh the lock file and run
  the review again before merging.
- Route Strix cross-provider fallbacks to explicit direct-OpenAI models
  (`openai-direct/...`) through the OpenAI inference endpoint instead of
  inheriting a provider-specific primary base: the workflow now provisions
  `STRIX_OPENAI_FALLBACK_API_BASE_FILE` (`https://api.openai.com/v1`), while
  standalone caller-supplied `LLM_API_BASE_FILE` values remain honored for
  OpenAI-compatible endpoints. Known GitHub Models, NVIDIA NIM, and OpenRouter
  bases are never inherited, and LiteLLM uses native OpenAI defaults only when
  no base is supplied. A non-https override fails configuration. This removes the NVIDIA-NIM-edge
  `404 page not found` that made the contracted final fallback unreachable
  after NIM exhaustion.
- Align stale `gpt-5.6-luna` test expectations with the valid `gpt-5.4`
  contract left behind by the earlier model rename.
- Honor each trusted base project's exact, integrity-bearing pnpm
  `packageManager` specification in OpenCode coverage images through the pinned
  Node distribution's Corepack runtime, instead of admitting the specification
  during materialization and then rejecting every version except pnpm 11.5.3;
  route generic coverage and docstring package scripts through the same
  Corepack boundary instead of invoking a removed bare `pnpm` binary.
- Review scans now run in a controlled order so each pull request receives a
  complete result instead of a rate-limit interruption. Open the pull request
  after the active scan finishes to review the latest result.
- Closed pull-request cleanup now preserves the review record and reports any
  authorization or malformed-data issue for follow-up. Reopen the pull request
  or update its credentials when the cleanup message asks you to act.
- Keep `--trust-lockfile` only for pnpm 11.3 and newer
  (`trustLockfile` landed in pnpm 11.3). pnpm 9, 10, and 11.0–11.2 reject
  that flag and previously failed LineageWeave JavaScript coverage before
  tests could run. Jest test scripts still receive `--coverage` because Jest
  documents a native coverage flag.
- Run declared JavaScript test scripts without synthesizing `--coverage` when
  the package does not declare a compatible coverage command, but keep the
  coverage result failed until the repository adds a lock-pinned provider and
  owned coverage command. A generic `c8`, `nyc`, or Istanbul dependency no
  longer makes an unrelated test runner receive an unsupported flag.
- Fix OpenCode coverage evidence for exact-base, organization-owned Python VCS
  dependencies without weakening registry hashes or the networkless PR sandbox,
  reject namespace, ambiguous, linked, native-extension, and installed-metadata
  layouts, and make exact roots readable by the unprivileged coverage user.

### Added

- Refresh the live product and technical gap baseline against the current
  open-PR queue after ContextualWisdomLab/.github#1252 merged, with SHA-bound
  snapshot rows, a same-session open/close delta, ADR Figma File ID N/A, and
  APA 7th doctoring. The inventory is not merge authorization.

- Classify Strix `ModelBehaviorError` and provider exhaustion as typed
  `STRIX_PROVIDER_UNAVAILABLE` evidence while preserving a nonzero required
  check. Incomplete scans and reported vulnerabilities both fail closed.

- Added an hourly organization commercial-readiness coordinator that discovers writable repositories, honors enabled dedicated writer leases and fully paginated live writer runs, refetches exact repository/workflow/run/PR state before dispatch, rotates bounded review-repair and opt-in NVIDIA OpenCode product-development targets, fails nonzero on fleet-wide inspection or dispatch outages, retains three-day JSON receipts, and keeps the existing 15-minute merge scheduler authoritative.
- Added a dedicated Quarantine Sandbox Runtime hourly caller at minute 14 that targets protected `develop`, dispatches at most one exact-head repair, applies a two-hour same-head retry floor, preserves non-cancelling single-flight execution, and maps only the established scheduler credentials with job-scoped OIDC.
- Added a dedicated OriginWeave hourly caller that invokes the product-neutral central scheduler with the exact repository, protected `main` branch, one-dispatch budget, two-hour same-head retry floor, non-cancelling single-flight heartbeat, job-scoped OIDC, and only the established scheduler credentials.
- Added a trusted pull-request comment router for `@cwl-noema-review` and review-only `@opencode-agent` dispatches, with an organization sweep, exact-head receipts, repository allowlisting, fixed runners, immutable checkout pins, and a permanent 100% statement/branch/docstring quality gate.
- Added an organization-owned reusable exact-artifact SBOM attestation boundary that validates inert six-file wheel/sdist evidence, binds CycloneDX 1.7 predicates to exact SHA-256 subjects, signs through least-privilege GitHub artifact attestations, and exports online and offline verification bundles.
- Added exact-base `uv.lock` materialization that reconstructs standalone nested projects with a checksum-pinned official `uv` exporter, isolated frozen/offline execution, strict exact-pin and SHA-256 output validation, and complete Python 3.10/3.14 quality evidence.
- Added a permanent exact-head contract workflow for the hourly review-repair scheduler, immutable reusable-workflow source, NVIDIA NIM model boundary, credential isolation, and fail-closed unattended-agent permissions.
- Added a dedicated Clearfolio hourly caller that invokes the product-neutral central scheduler with the exact repository, protected base branch, one-dispatch budget, one-hour retry floor, single-flight concurrency, and only the established scheduler credentials.
- Added a dedicated DiskSage hourly caller that invokes the same product-neutral RCA and remediation-feasibility scheduler with an exact repository target, one-dispatch budget, two-hour same-head retry floor, non-cancelling single-flight heartbeat, and explicit established scheduler credentials.
- Added a dedicated fast-mlsirm hourly caller that preserves Rust-owned psychometric arithmetic while dispatching at most one exact-head, root-cause-driven repair with a two-hour same-head retry floor.
- Added a dedicated Orgmetra hourly caller at minute 58 that targets protected `develop`, dispatches at most one exact-head repair, preserves a two-hour same-head retry floor and non-cancelling single-flight execution, and maps only the established scheduler credentials.

### Changed

- Require the PR Review Merge Scheduler to observe both GitHub's aggregate
  `APPROVED` decision and the latest effective non-author, non-OpenCode formal
  approval bound to the exact live head before direct merge or auto-merge.
  A later same-head change request revokes that reviewer's earlier approval,
  and existing auto-merge is disarmed when either authorization is absent.
- Emit completed repository pull-list requests as they finish in the five-minute
  agent-mention sweep, while retaining the four-worker ceiling, rotation, and
  exact-name dispatch ledger, so one slow repository cannot hide ready sibling
  repositories.
- Require the hourly repair worker to establish an exact-head root cause, enumerate the smallest remediation candidates, and prove writer authority, sealed-path scope, credentials, dependency order, verifiability, and causal effect before editing; infeasible or external blockers leave the tree unchanged while the broader loop continues with another eligible PR or buyer-visible product gap.
- Run the bounded Quarantine Sandbox Runtime heartbeat at minute 14 without granting the caller model secrets, repository mutation permissions, approval, merge, release, artifact-execution, or final security-verdict authority.
- Run the bounded Clearfolio PR review-feedback repair caller at minute 23 of every hour while keeping the shared scheduler free of product-specific timers and repository names for modular reuse by naruon, contextual-orchestrator, Inkspan, and other CWL services.
- Run the bounded DiskSage repair heartbeat at minute 37 of every hour, dispatch no more than one exact-head repair, and wait two hours before redispatching an unchanged head so legitimate OpenCode or NVIDIA NIM latency does not create duplicate writers.
- Run the bounded fast-mlsirm repair heartbeat at minute 49 of every hour with one-dispatch scope and a two-hour same-head floor, without weakening true-parameter recovery, CPU/GPU parity, skipped-test, or Rust-ownership gates.
- Use NVIDIA NIM `mistralai/mistral-small-4-119b-2603` with explicit high reasoning for scheduled repair and `nvidia/nemotron-3-nano-30b-a3b` for bounded helper work instead of GitHub Models in the write-capable autofix worker.
- Apply one NUL-delimited exact-path and complete pre/post-worktree verification contract to both ordinary review repair and merge-conflict repair rather than relying on a visible post-model diff for the ordinary path.

### Changed

- Avoided the expensive R/testthat failure-summary regular expression on marker-absent bounded logs by checking the required terminal marker first, while preserving fail-closed handling for incomplete or malformed failure evidence.

### Fixed

- Keep the central required-workflow coverage placeholder from superseding a
  failed repository-dispatch coverage run; coverage retry and merge decisions
  now use authoritative execution evidence for the central scheduler.
- Re-dispatch an exact-head OpenCode review after its coverage-only blocker is
  cleared, selecting the newest coverage rerun by timestamp across workflow
  names and ignoring only the superseded `opencode-review` failure and central
  required-workflow placeholder. Conflicting heads and failed sibling jobs in an
  OpenCode workflow remain fail-closed alongside unresolved threads, Strix,
  coverage, and unrelated failed checks.
- Web verification now checks services through local readiness addresses only.
  Start the backend and frontend on this computer and use their local health
  URLs when running the check.
- Review results now separate cosmetic notices from blocking failures. Open the
  failure details and correct the requested issue before running the check
  again.
- Resolve Strix visibility from the trusted GitHub event for ordinary push,
  schedule, and pull-request runs, reserving API retries for cross-repository
  dispatches whose workflow token may not see the target repository.
- Reconciled the Strix required-workflow smoke contract and the privileged
  OpenCode model pool with the current `gpt-5.4` direct-OpenAI fallback after
  `gpt-5.6-luna` was retired. This prevents every consumer repository's
  required Strix check from failing on a stale central assertion or selecting a
  nonexistent direct model.

- Publish only the sanitized cumulative Strix report tree, avoiding a later
  copy of relative scanner output that could reintroduce known internal warning
  text into uploaded security evidence.

- Retry configured Strix fallback models when the primary provider records a
  rate-limit or infrastructure failure only in its structured report log, and
  evaluate each fallback against its newest report without letting an older
  failed attempt poison a complete later report.

- Include the exact `backend/app/*.py` package context in PR-scoped Strix
  scans when a module in that package changes. The trusted resolver uses a
  NUL-delimited exact-head tree listing, copies unchanged dependencies from
  the trusted base, and keeps changed-file attribution and provider failures
  fail-closed.
- Include the exact `contextual_orchestrator/*.py` sibling-import context under
  the same NUL-delimited exact-head and fail-closed path boundary without
  expanding changed-file finding attribution.
- Treat Rust source and Cargo manifests as governed Strix inputs and include
  trusted Cargo, toolchain, and `deny.toml` context when a workflow change
  scopes a Rust workspace.
- Run Strix with an explicit canonical scan target from a temporary working
  directory outside that target, so scanner state and relative reports cannot
  become self-scanned source findings; preserve those reports as gate evidence.
  PR-scoped Python scans also include the PostgreSQL introspection security
  helpers when that package exists in the target repository. PR scopes now live
  below the gate's private runtime directory so unrelated temporary-file
  cleanup cannot remove scan input during PR-head materialization.
- Classify Strix `ModelBehaviorError` with zero reported vulnerabilities as
  retryable model-protocol evidence, while keeping `Vulnerabilities [1-9]` and
  other severity signals fail-closed.
- Derived `org-queue-sweep`'s rotation index (added in `ContextualWisdomLab/.github#1220` to stop the walk-order starvation from `ContextualWisdomLab/.github#1219`) from a persistent `ORG_SWEEP_ROTATION_COUNTER` repository variable incremented by exactly one at the start of every actual sweep execution, instead of `github.run_number` (which increments on every trigger of this workflow, not only the sweep schedule — Devin review finding on `#1220`) or a wall-clock tick alone (which can repeat an offset when this single-flight, up-to-60-minute job runs behind schedule by an exact multiple of the repository count — CodeRabbit review finding on `#1223`). Falls back to the wall-clock tick only if the persistent counter itself is unavailable, so a fairness mechanism never blocks the sweep's review-dispatch/merge work.
- Retried the Strix scan up to `STRIX_TRANSIENT_RETRY_PER_MODEL` times, same model, when the log shows the upstream strix-agent Caido sandbox bootstrap timing race (`loginAsGuest failed after N attempts` / `Failed to connect to 127.0.0.1 port <port>`; tracked upstream as usestrix/strix#1036, #1037, #1056). A slow CI runner can exceed strix-agent's fixed 10-attempt sandbox-login budget before its local intercepting proxy is reachable, even though the penetration test itself never started and no vulnerability evidence was produced or lost; the Docker image is already cached from the failed attempt, so a same-model retry is cheap and typically clears the one-off boot race. Not wired into cross-model fallback, since switching LLM models cannot change local sandbox container boot timing.
- Replaced nonexistent `job.workflow_repository` / `job.workflow_sha` / `job.workflow_ref` / `job.workflow_file_path` context references (actionlint: "property ... is not defined in object type") in `pr-review-fix-scheduler.yml`'s called-workflow source verification and `exact-artifact-sbom-attestation.yml`'s trusted-verifier checkout. Both always failed closed on the missing properties (ContextualWisdomLab/.github#1212) or, for the SBOM attestation checkout, silently resolved an empty repository/ref instead of the pinned trusted source (downstream `gh attestation verify --signer-repo`/`--signer-workflow`, using the separately hardcoded `SIGNER_REPOSITORY` constant rather than any workflow_ref, still failed closed on the resulting empty signer identity). `github.workflow_ref`/`github.workflow_sha` are real, documented properties, but for a `workflow_call` target they reflect the top-level *calling* workflow, not the reusable workflow's own file — a prefix match against the reusable workflow's own path can never succeed. `exact-artifact-sbom-attestation.yml`'s checkout now uses `github.workflow_sha` (correct today: it has no callers yet); `pr-review-fix-scheduler.yml`'s identity check instead validates `github.repository`, since every current caller uses a local, same-repo `uses: ./...` where caller and callee share one commit and `github.workflow_sha` is still the right pin. Tracked follow-up for the SBOM attestation checkout once a real (potentially cross-repo) caller exists: ContextualWisdomLab/.github#1228.
- Used the receiving repository's workflow token for same-repository scheduler
  Actions inventory and read calls, while retaining the established mutation
  credential chain. An exhausted organization-wide OpenCode App installation
  budget can no longer prevent a central `.github` PR from dispatching its
  exact-head review; cross-repository targets still require an explicit
  credential.
- Kept independently valid root-level Python lock environments separate during
  trusted base coverage installation. A directory with more than two candidate
  locks no longer collapses unrelated OpenCode, security, and application
  environments into one impossible resolver transaction; incomplete hash
  closures remain skipped, while each complete hash-pinned closure installs
  independently.
- Rotated `org-queue-sweep`'s repository walk order by the workflow's own run number before applying the shared organization-wide review-dispatch/branch-update budget, so a fixed early repository in the unsorted `gh api /orgs/{org}/repos` walk order can no longer permanently starve every later repository's ready, all-green, zero-open-thread pull requests of the single per-tick dispatch (`ContextualWisdomLab/.github#1219`). The total per-tick budget is unchanged; only which repository consumes it rotates.
- Forward `trigger_reviews=true` explicitly from the trusted OpenCode mention wrapper to the authoritative scheduler while retaining GitHub's ten-key dispatch limit. Source-comment identity remains bound in the verified invocation claim and durable ledger instead of occupying an unused scheduler field, so a successfully routed `@opencode-agent` request now dispatches review work rather than entering queue maintenance with reviews disabled.
- Allowed an allowlisted base repository's open fork-head PR to enter the central exact-head OpenCode review path. The scheduler and privileged reviewer still re-read the live PR, bind base/head refs and SHAs, reject malformed repository identities, keep fork source as untrusted data, preserve the existing maintainer-writable update rule, and reserve the final external-head merge for a maintainer.
- Confined OSV base and head repository checkouts to the same `source/` child directory, so a cross-fork head checkout can replace that repository without deleting the base-scan JSON held at the workspace root. Both scans retain identical source paths and the required base/head vulnerability comparison remains fail-closed.
- Restored 100% docstring coverage for the commercial-readiness GitHub transport constructor.
- Refused PR Review Merge Scheduler head mutations, `update-branch` and the last-push approval head restamp, whenever the resolved mutation credential is the workflow `GITHUB_TOKEN`. GitHub starts no workflow run for events created with that credential, so the moved head collected no current-head required checks and the PR stayed permanently `BLOCKED` with a `github-actions[bot]` merge commit that no later scheduler run could repair, because the branch was no longer behind. The scheduler now waits with `head_mutation_credential_upgrade` guidance naming `PR_REVIEW_MERGE_TOKEN`, `OPENCODE_APPROVE_TOKEN`, and the OpenCode app token exchange.
- Parsed `opencode.jsonc` as JSONC (stripping `//` and `/* */` comments outside string literals) in the reasoning-effort guard and its contract tests, instead of raw `json.loads`, which rejected the file the moment it carried its first explanatory comment (added for the `contextual-orchestrator` provider block) with `Expecting property name enclosed in double quotes`. Comment markers inside string values, such as the `$schema` URL, are left untouched.
- Download the pinned `uv` 0.12.1 exporter from the official GitHub Releases URL instead of `releases.astral.sh`, which now returns HTTP 403 and blocks org-wide OpenCode `coverage-evidence`. The SHA-256 pin is unchanged. The opener may follow one hop onto `release-assets.githubusercontent.com` or `objects.githubusercontent.com` and still rejects every other host, userinfo, non-HTTPS scheme, and nondefault port (ContextualWisdomLab/.github#1109).
- Compared the trusted `uv` executable's post-install `--version` output against the real GitHub Releases build's full string, `uv 0.12.1 (x86_64-unknown-linux-gnu)`, instead of the bare `uv 0.12.1` the prior check required; the genuine release binary always prints the target triple, so every installation was failing the pin check immediately after the archive download itself was fixed (ContextualWisdomLab/.github#1109).
- Excluded relative `-r` and `--requirement` referrers from generated flat base-lock publication while retaining bounded include syntax diagnostics and discovering independently complete direct `.txt` children of `requirements` directories.
- Bound the central Semgrep job to one `SEMGREP_IMAGE` digest for log evidence, manifest inspection, and `docker run`, so a buyer reconstructing the scan can prove the logged scanner is the scanner that ran.
- Published substantive OpenCode LLM probes when they already carried an independent proof and exact source-line digest but omitted a duplicated `path:line` citation, so NVIDIA NIM / OpenCode review evidence is no longer discarded as `NO_CONCLUSION`.
- Refused a conflict-scope repository root whose immediate parent is a symbolic link, so a swapped parent cannot redirect the canonical worktree after the last-component check (CWE-367).
- Materialized base Python locks only when every package line is an exact SHA-256 pin or a bounded relative `-r`/`--requirement` include. A lone `--require-hashes` directive, a dotted include such as `./lock.txt`, or `-r other-hashes.txt` no longer enters the trusted build context.
- Bounded the Strix quality self-test's deterministic timeout fixtures to 3-second process and 5-second fake-sleep budgets so exact-head policy evidence completes inside the existing job limit without changing production Strix scanner timeouts, providers, credentials, or review semantics.
- Allowed commas and ASCII parentheses in the bounded Strix changed-file path policy so legal tracked Packrat fixtures can receive exact-head security analysis, while rejecting raw `..` components before normalization and keeping controls, backslashes, whitespace ambiguity, and shell punctuation fail-closed.
- Bound each review-agent invocation key to the wrapper's complete canonical payload, including the base branch and requesting actor; altered fields with a valid-format key now fail before durable-leader election or forwarding, and wrapper write permission is job-scoped.
- Hardened exact-artifact SBOM verification with strict finite RFC 8259 JSON, integer CycloneDX document versions, deterministic UUIDv5 subject identities, exact filename properties and single SHA-256 root bindings, environment-only shell input transfer, pinned Ubuntu 24.04 quality runners, and checksum-sealed beginner-readable offline evidence.
- Bound both trusted-uv quality jobs to `github.event.pull_request.head.sha` and added a permanent two-checkout regression contract so exact-head compatibility, coverage, docstring, and compilation claims cannot silently measure GitHub's generated pull-request merge revision.
- Made Strix treat only a single LiteLLM provider-error line containing NVIDIA NIM context and model-catalog 404 evidence as cross-model fallback evidence, rejecting cross-line signal assembly and provider-like target source literals; moved the public default to Nemotron 3 Super 120B and added a second NVIDIA hosted candidate before GitHub Models without neutralizing reported vulnerabilities.
- Bind reusable scheduler implementation to the validated called-workflow repository, SHA, ref, and file path, and verify the checked-out commit before executing privileged scheduler logic.
- Removed the ambiguous central-repository schedule fallback that could scan `.github` instead of Clearfolio when no external variable was configured; the active product caller now names Clearfolio explicitly while the reusable engine retains caller and dispatch overrides.
- Corrected the conflict-ordering regression contract to select the conflict-specific snapshot and verification after the ordinary path adopted the same trusted helper.
- Retried the Strix target-repository visibility lookup up to six times with linear backoff before failing closed, matching the existing PR-head-fetch retry convention in the same workflow. A single transient `gh api` failure (observed as a shared GitHub App installation token hitting its hourly rate limit while dozens of org repositories run hourly review schedulers concurrently) previously failed the entire required Strix check immediately, blocking otherwise mergeable, fully reviewed pull requests fleet-wide with no code defect involved.

### Security

- Fail closed when GitHub dependency-review evidence is unavailable (non-200, transport failure, or truncated compare) instead of treating HTTP 403/404 as a clean skip; the probe checks out the exact head SHA and never prints the API body.
- Keep the Quarantine Sandbox Runtime caller read-only and model-secret-free, grant only job-scoped OIDC to the reusable scheduler, and preserve the product boundary in which the sandbox returns artifact-analysis evidence while hosts retain WAF/IDS, admission, final verdict, incident, and retention authority.
- Reject `.github/` and `scripts/ci/` from review-thread-derived autofix path authority so an untrusted inline reviewer cannot authorize the write-capable repair agent to modify workflows, CODEOWNERS, actions, scheduler code, or CI helpers that govern its own control plane.
- Require the model-write snapshot and exact-path allowlist to remain outside the pull-request worktree, checking both absolute and resolved locations so repository-local controls and outside-looking symlinks resolving into the repository fail closed before they can authorize or verify model changes.
- Snapshot the complete pre-model worktree for ordinary and conflict repair and reject every model-caused created, deleted, modified, mode-changed, retargeted, ignored, dangling, directory-backed, external-link, metadata-race, or out-of-scope path before staging or push.
- Add ignored-path inventory through Git's tracked, other, and `--others --ignored --exclude-standard` views so model-created caches, credentials, or build output cannot evade comparison merely because ordinary Git publication omits them.
- Deny `.git` and `.git/*` in both OpenCode permission maps, disable repository hooks for privileged commit and push through `core.hooksPath=/dev/null`, and push only to an explicit revalidated repository URL so model-mutable Git metadata cannot control publication.
- Keep the Clearfolio caller and reusable scheduler read-only at workflow and job scope; authorize mutation only through explicitly mapped `PR_REVIEW_MERGE_TOKEN`, `OPENCODE_APPROVE_TOKEN`, or the short-lived OpenCode GitHub App token exchanged from OIDC, with explicit pre-write guards and no `github.token` mutation fallback.
- Keep the DiskSage caller read-only and pass only the established scheduler credentials; do not inherit secrets, expose the NVIDIA NIM model credential to the queue scanner, use a GitHub Copilot token, or grant the caller repository mutation permissions.
- Keep the fast-mlsirm caller read-only and model-secret-free; preserve independent approval, exact-head evidence, and Rust production-arithmetic ownership while centralizing only bounded review repair.
- Bind `NVIDIA_NIM_API_KEY` only to the two OpenCode model execution steps, fail closed when the secret is absent, and remove GitHub and Actions OIDC credentials from both model subprocesses. The decision record now cites CWE-367 so a later default-branch push cannot replace privileged repair helpers after `repository_dispatch` has already selected the workflow revision.
- Recorded the org control-plane architecture, including the hourly NVIDIA NIM repair gate, so agents reconstruct the write-capable worker trust boundary from the repo instead of private memory.
- Deny unnecessary non-file OpenCode interactions and preserve the independent read-only reviewer workflow and its credential/model-pool contract byte-for-byte.
- Pin the repository-dispatch autofix helper checkout to the exact workflow-run SHA rather than a moving default branch.
- Pass only `PR_REVIEW_MERGE_TOKEN` and `OPENCODE_APPROVE_TOKEN` from the Clearfolio schedule caller; do not use `secrets: inherit` and do not expose the NVIDIA model credential to the queue-scanning workflow.

### Documentation

- Added Quarantine Sandbox Runtime operator and APA 7 doctoring for the hourly RCA loop, source-agnostic leaf boundary, protected-`develop` activation, bounded retry cadence, OIDC and secret scope, independent approval, verification, and rollback.
- Rewrote the root README for org operators and sibling-repo maintainers: org profile plus central required workflows, standalone run, and how siblings consume ruleset `18156473` without copying workflow files. Moved bot/agent PR-review procedure to `docs/pr-review-and-merge-procedure.md`.
- Retargeted the Strix quality-gate prose contract to the review procedure document.
- Added an APA 7 doctoring record for conflict-control evidence isolation, including the Strix-reported trust-boundary failure, test-first remediation, canonical-path rule, operator contract, rollback, MITRE CWE-22, and current GitHub Actions secure-use guidance.
- Added operator and APA 7 doctoring records for the hourly cadence, immutable source identity, NVIDIA NIM provider and secret boundary, high-reasoning Mistral Small 4 writer, model-process credential isolation, modular MSA ownership, product-specific caller activation, verification contract, and rollback.
- Added DiskSage operational documentation for the hourly RCA loop, bounded retry cadence, permission model, standalone and MSA reuse, verification, rollback, and APA 7 references.
- Added fast-mlsirm operational documentation for the hourly RCA loop, psychometric scientific gates, Rust ownership, bounded retry cadence, credential isolation, modular reuse, rollback, and APA 7 references.
- Documented the ordinary and conflict repair write-scope parity, ignored-path and symlink inventory, Git-control-file denial, hook suppression, explicit push destination, RED/GREEN evidence, operator response, and local-versus-protected evidence boundary.
- Documented the review-authentication boundary that excludes autonomous writer control-plane paths from review-derived file authority, its test-first Strix security evidence, exact-head coverage contract, and rollback prohibition.

- Added an organization-owned reusable exact-artifact SBOM attestation boundary that validates inert six-file wheel/sdist evidence, binds CycloneDX 1.7 predicates to exact SHA-256 subjects, signs through least-privilege GitHub artifact attestations, and exports online and offline verification bundles.
- Hardened exact-artifact SBOM verification with strict finite RFC 8259 JSON, integer CycloneDX document versions, deterministic UUIDv5 subject identities, exact filename properties and single SHA-256 root bindings, environment-only shell input transfer, pinned Ubuntu 24.04 quality runners, and checksum-sealed beginner-readable offline evidence. The decision record now cites Bray (2017) so NaN and Infinity cannot be treated as sealed SBOM numbers.
- Recorded the org control-plane architecture, including exact-artifact SBOM attestation, so agents reconstruct the signing trust boundary from the repo instead of private memory.
