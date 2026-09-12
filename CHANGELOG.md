Warning: truncated output (original token count: 37557)
Total output lines: 1483

### Failed-check finding names the Strix sandbox instead of the gateway

- `opencode-review-dispatch.yml`'s `emit_strix_provider_failure_finding` rendered one fixed finding for every `STRIX_PROVIDER_UNAVAILABLE` line, whose Root cause read "The contextual-orchestrator gateway or its discovered provider pool was unavailable for this run". `#1953` had just given the Strix sandbox bootstrap failure its own second verdict token (`STRIX_SANDBOX_UNAVAILABLE`) precisely because that attribution is wrong for it -- the sandbox container never reaches its Caido proxy, so the run dies before the gateway serves anything -- and this consumer re-applied the wrong attribution one step downstream, into the review findings and the failure census. The emitter now branches on the second token: a sandbox verdict gets a finding that names Strix's sandbox, says the verdict does not name the gateway, and tells the reader not to change gateway or provider configuration on its strength. A `STRIX_PROVIDER_UNAVAILABLE` line without the token keeps its existing text verbatim, so the gateway class has no regression surface. No test covered this finding text at all before (`gateway or its discovered provider pool` matched nothing under `tests/`); `tests/test_opencode_dispatch_strix_sandbox_finding.py` now runs the production emitter from the published run block and pins both directions plus the no-signal case. Refs #1953, #1935.

### Strix gate keeps a recovered transient model error from failing a completed scan

- `scripts/ci/strix_quick_gate.sh` `sanitize_known_strix_report_warnings` now also strips strix-agent's `strix.core.execution: transient model/provider error for <agent>; replaying turn (attempt n/m, backoff Ns): …` WARNING lines before the report failure-signal scan. strix-agent 1.5.3 (`strix/core/execution.py:763`) emits that line only inside its bounded transient-retry branch, immediately before the replay runs; an exhausted retry logs `agent run failed for …; marking failed` at ERROR with a traceback and exits non-zero, and both of those still fail the gate. Observed on `.github#1689` run `34013778497`: a completed 63-minute scan (`run.json` `completed`, SARIF 0 results, attempt exit 0) was failed closed as `STRIX_PROVIDER_UNAVAILABLE … exhausted` on three such warnings, and the scheduler then dispatched another same-head scan. The pattern is anchored before the exception repr so the same class keeps matching after a gateway pin advance changes the exception type; re-verify the message format on every strix-agent bump. One documented side effect: when a provider's 503 body appears only inside a retry line's exception repr, removing that line also removes the only text `has_strix_report_provider_failure_signal` would have matched in the report log, which can make `is_model_retryable_error`'s report-only branch read a genuine outage as non-retryable. The direction is fail-closed (an exhausted retry still exits non-zero with its ERROR and traceback retained), and with a contextual-orchestrator primary the verdict branch answers before that classifier is consulted, so no path today changes its outcome; if fallback-model classification is ever wanted for a non-gateway primary, read the pre-sanitize attempt copy that `preserve_attempt_log` already keeps. Tests: `tests/test_strix_recovered_transient_sanitizer.py`.

### Review sidecar preflight postpones a rate-limited account's candidates instead of banning them

- `_preflight_review_agents` no longer ends its walk when every credential account has answered 429 twice in a row. A candidate set aside by `REVIEW_PREFLIGHT_ACCOUNT_SKIP_AFTER_429` is postponed to the end of the walk, and once the first pass ends with the readiness target unmet and probe budget left, the postponed candidates are probed in catalog order until the sixteen-probe budget is spent. On 2026-09-06 five sidecar boots whose probes began between 07:24Z and 08:05Z read `probed 6 / skipped 18 / ready 0` and failed closed: `.github` run 34016207820's six probes across all three accounts were refused 429 between 07:49:35.111Z and 07:49:35.767Z, so the rule set every account aside on two same-account requests about 310 ms apart and gave up with ten of sixteen probes unspent — and because deferral needs one ready route, nothing was served either; `keyverse#143`'s 08:20Z `noema-review` repeated it in a second repository (six probes, 369 ms, all 429). The pools are not dead in those minutes: run 34016093772 was inside its own preflight during that burst, and its `llama-3.2-11b` probes on the same two NVIDIA keys answered ready at 07:50:58.7Z and 07:50:59.0Z, 84 seconds after those keys refused. Whether the unspent probes would have found a ready route inside a burst is unmeasured and is not claimed; the change is justified by ending a walk under target with the budget in hand. Of the fourteen boots that ran the merged rule, eight spend all sixteen probes in the first pass and are unchanged; one (`argos` 34014143870, a serving boot at `12 / 12 / 3`) exhausts its candidates under budget and now gains a second pass, as do the five burst boots. The cost is stated rather than assumed: a refused probe costs about 120 ms, a silent one up to the 90 s receive timeout, and the postponed tail holds both (`google/gemma-4-31b-it` answered `TimeoutError` in 15 of the 19 probes that reached it), so the worst case adds up to about 15 minutes to a boot that still fails and the two-stage auto path goes from 8 to 24 requests including the priced stage. The second pass never draws on the shared escalation budget, so the priced fallback keeps the escalations it had. The report gains `postponed_probed_count` (`skipped_count` now counts postponed candidates the budget never reached) and, on a refused probe, `retry_after_s` when the response carried a whole-seconds `Retry-After` header — evidence only, nothing waits on it, so the next census can decide whether a delayed second pass is worth proposing. ADR-0029 is amended. Refs #1948, #1949.

### Superseded OpenCode review dispatches coalesce before they take a runner

- `opencode-review-dispatch.yml` now carries a workflow-level `concurrency` group keyed by the dispatched pull request (`opencode-review-dispatch-<target repository>-<pr number>`, `cancel-in-progress: true`), matching `codeql-scan-dispatch.yml`'s workflow-level group and the rationale already recorded in `strix.yml`, `noema-review.yml` and `opencode-review.yml`: a job-level group is never evaluated while the whole run waits behind the organization job ceiling. The workflow kept its group only on the long `opencode-review-target` job, so two dispatches for one pull request each queued for hours and each was allocated a runner before the older one could be discarded. Measured on 2026-09-06: four of the five dispatch runs that passed `validate-pr-metadata` were rejected hours later by the privileged metadata check because the head had moved while they queued (runs `34002473295`, `34010256951`, `34015973300`, `34016922761`), each after `coverage-source-tree` and `coverage-evidence` had run. The privileged check itself is unchanged -- it rejected exactly what it should; what changes is that the superseded run is now cancelled at creation instead of spending a slot to discover its subject moved.

### Strix gate names the sandbox bootstrap failure and retries it once

- `scripts/ci/strix_quick_gate.sh` gives the Caido sandbox bootstrap race (`loginAsGuest failed after 10 attempts` on `127.0.0.1:<port>`, upstream usestrix/strix#1036/#1037/#1056) its own bounded same-model retry budget, `STRIX_SANDBOX_BOOTSTRAP_RETRIES` (default 1), drawn on top of `STRIX_TRANSIENT_RETRY_PER_MODEL`. That budget is 0 in production because the gateway owns model failover, so the documented sandbox retry never ran: `argos` Strix run 34013128112 (2026-09-06) shows one attempt, `Docker image ready`, the proxy never reachable, Strix exiting after 240 s -- while the sidecar reported four ready and four deferred routes that were never called. The budget is charged in the same branch that grants the attempt, so a log matching the sandbox class together with a gateway class cannot extend the loop without charging it (caught by adversarial review of the first draft). The primary-scan verdict for that class now reads `STRIX_PROVIDER_UNAVAILABLE: STRIX_SANDBOX_UNAVAILABLE: the last Strix attempt ended in the sandbox bootstrap (...) after N sandbox-specific same-model retries (budget B); this verdict names Strix's sandbox, not the LLM gateway.` instead of `orchestrator/free exhausted`, stating only what the gate observed; the leading token is unchanged so the workflow's finding-free classification and its tests are untouched, and the second token lets the review census split sandbox outages from gateway ones (two of six recent Strix artifacts were this class). Refs #1948.

### Review sidecar preflight fills the served set lazily to a readiness target

- `_preflight_review_agents` now treats the catalog as a candidate list, probed in its tier-then-round-robin order until `REVIEW_PREFLIGHT_TARGET_READY = 8` routes are ready or `REVIEW_PREFLIGHT_MAX_PROBES = 16` probes are spent (ADR-0029). The two-stage candidate budget rises from 12 to 24 (`REVIEW_PREFLIGHT_MAX_TOTAL_ROUTES`; auto pool split 16 free / 8 priced; the sidecar's and the launcher's `ORCHESTRATOR_CATALOG_LIMIT` defaults follow), the production `free` pool lists all 24 (12 before), and the per-account cap stays 8. An account that answers 429 to `REVIEW_PREFLIGHT_ACCOUNT_SKIP_AFTER_429 = 2` consecutive probes has its remaining candidates skipped without a probe (a 429 is a per-key answer), so the probes it would have spent reach the other accounts' next candidates — under the real 2026-09-06 order that is the difference between about five ready routes and the target of eight — and a fully rate-limited hour costs two probes per account instead of the whole budget; the report gains `skipped_count` and `account_skip_after_429`. The sidecar's job-log echo of the preflight JSON grows from 160 to 400 lines so 16 probed routes are not cut off exactly in the dead hour the summary matters. A permanently dead candidate -- NIM lists `gemma-3-12b`/`gemma-3-4b` and answers 404 on every run -- now costs one probe instead of a served slot, and a healthy pool stops early instead of always probing every candidate. Motivation: after #1939's four-per-account slice each NVIDIA key's slots were its first four models alphabetically, two of them those 404s, so preflight readiness fell from 6/12 to 1–3/12 and `noema-review` on this repository went from 7 successes / 14 failures to 0 / 22. The report gains `candidate_count`, `target_ready` and `probe_budget`; `probed_count` counts probes actually sent. ADR-0003's stage-budget sentence is amended. Refs #1939, #1947, #1948.

### Sidecar sanitizer keeps the exception type and innermost frame per traceback

- `scripts/ci/sanitize_contextual_orchestrator_sidecar_stream.py` now reduces each Python traceback in the sidecar stream to one line, `unexpected_exception type=<ExceptionType> frame=contextual_orchestrator/<module>.py:<line>:<function>` (the type identifier and the innermost package frame only; the exception message, source echoes and non-package frames are never re-emitted; a traceback cut off by the sidecar dying or without a package frame reports `unknown`). The previous single, once-per-stream `sidecar emitted an unexpected exception` line kept neither the count nor the type: `.github#1812`'s strix run (33993155419) ended on 83 gateway `500 internal_error` responses -- the orchestrator's generic request handler prints one traceback per unhandled exception -- and no artifact could say which exception escaped or where. Chain sentences (`During handling of the above exception…`, `The above exception was the direct cause…`) are consumed, so a chained exception yields cause then effect.
### Contextual-orchestrator pin advance fixes orchestrator/free retry-stacking

- Advanced the central sidecar's pinned immutable CO revision from `2e414d15` to protected `main@414f22973658c4ddc3d4320fcf7acd9b4e8ba991`, carrying contextual-orchestrator#1081's fix into Strix, OpenCode, and Noema. Root cause: `TaskOrchestrator._invoke`'s own retry-then-failover decision for a retryable 5xx (budgeted `1 + tool_retry_attempts` real tries per candidate) was getting multiplied by `ModelClient._send_with_retry`'s independent transient-retry-with-backoff underneath it (`max_retries + 1` further tries per call) -- up to 6 real network attempts against one already-flagged-flaky `orchestrator/free` agent before `_invoke` ever tried the next ranked candidate. Confirmed as the cause of independently observed incidents in #1912, #1231, #1503, and #1198, each spending 9-57+ minutes on one escalated route and surfacing that same route's model in its final error, never reaching a cleanly-ready sibling preflight had already found. The fix (`ModelClient.single_attempt_transport()`) changes only which agent gets tried next; no per-attempt timeout changed. Reproduced the bug directly against unmodified contextual-orchestrator `main` before the fix (6 real attempts) and confirmed the fix resolves it (<=2) before advancing this pin. `docs/adr/0003-contextual-orchestrator-vendored-free-zdr.md`'s 2026-09-06 amendment and `tests/test_contextual_orchestrator_review_sidecar_contract.py`'s `ORCH_PIN_SHA` were updated alongside this pin. All callers still consume an exact SHA; no branch or tag is introduced.

### Review sidecar preflight keeps transient-rejected routes as deferred failover

- `_preflight_review_agents` no longer discards a route whose 16-token probe answered with a status the serving gateway itself retries and fails over across (`408 409 425 429 500 502 503 504 529`, the vendored orchestrator's `TRANSIENT_HTTP_STATUS`). Such routes are kept as **deferred**, ranked after every ready route by a catalog-priority penalty, so a stalled or rate-limited ready route has somewhere to fail over to; `ready_count` is unchanged, a new `deferred_count` is reported, and `rejected_count` covers only routes the gateway would not retry either (404, auth failures, invalid responses). With no ready route the stage still fails as before, so ADR-0005's priced-catalog fallback contract is untouched. Motivation: `noema-review` run 33993637015 (2026-09-05) rejected 11 of 12 routes -- six with 429, three of them on NVIDIA keys whose sibling routes were ready -- served the single ready route for 542 s and returned 502; under this rule the same run would have served 1 ready + 6 deferred. The sanitized stream gains a `preflight_route_deferred` line alongside `preflight_route_rejected`.

### Noema review ships sidecar evidence on failure

- `noema-review.yml` now uploads `strix_runs/contextual-orchestrator-sidecar.stderr.log` and `strix_runs/contextual-orchestrator-preflight.json` as the `noema-sidecar-evidence` artifact when the verdict phase fails (`if: failure()`, the same pinned `actions/upload-artifact` Strix uses, `if-no-files-found: ignore`, 5-day retention). Until now a failed Noema run left `artifacts=0` -- run `33981136873` spent 3122 s walking six ready routes twice each and ended in HTTP 502 with no per-route trace anywhere but the sidecar's stderr -- so the only diagnosis available was the caller's one-line summary. The stderr file is the sanitizer's bounded allowlist output (`sanitize_contextual_orchestrator_sidecar_stream.py`), the same file Strix already publishes in `strix-reports`; per-attempt route outcomes still need an allowlisted structured line from the orchestrator to appear in it. Refs #1935, #1939.
### Sidecar sanitizer admits orchestrator route and circuit events

- `scripts/ci/sanitize_contextual_orchestrator_sidecar_stream.py` now passes the orchestrator's own `provider_attempt`, `provider_attempt_failed` (cut before the free-text `error_message=`), `provider_backoff`, `provider_exhausted`, `provider_rejected_permanent`, `provider_no_retry_budget` and `circuit_failure|opened|reset|cleared` lines (whose `failures`/`reset_seconds` are floats at runtime, `2.0`/`30.0`), matched field by field against bounded identifier and number charsets, with either Python's default `LEVEL:name:` prefix or the sidecar formatter's `asctime LEVEL name` prefix (the timestamp is kept so per-route durations can be read as differences). Until now every one of these lines was folded into `omitted_unstructured_lines`, so the `provider_exhausted` WARNING that already fires today after a route's retry budget is spent never reached an artifact, and a 3122 s walk across six ready routes (run `33981136873`) had no per-route trace. Companion to #1943 (sidecar DEBUG logging) and #1944 (Noema uploads the file on failure). Refs #1935, #1939.
### Review sidecar records the orchestrator's per-attempt trace

- `contextual_orchestrator_review_launcher.py` now configures the orchestrator process's logging before serving (`_configure_sidecar_logging`, calling the vendored `contextual_orchestrator.debug_logging.configure_logging`), defaulting to `DEBUG` with a timestamped format and overridable through `ORCHESTRATOR_SIDECAR_LOG_LEVEL`. The orchestrator logs every provider attempt, its classified failure, backoff, and circuit event at `DEBUG` and only `provider_exhausted`/`circuit_opened` at the default `WARNING`, so a failed review left no way to see which routes were tried or how long each took: a 3122 s `noema-review` 502 on 2026-09-05 could only be attributed to "six ready routes, two retry layers, about 548 s per hop" by reading source, not the log. None of the `DEBUG` sites at the vendored pin carries prompt or response content, and the sidecar already pipes this stderr through the redacting sanitizer before it is written to `strix_runs/contextual-orchestrator-sidecar.stderr.log`; a companion change uploads that file as a failure artifact.

### Review sidecar catalog interleaves credential accounts

- `build_zdr_prioritized_catalog` now fills each free/ZDR tier round-robin across independently credentialed accounts instead of in provider-name order. The sidecar exports `ORCHESTRATOR_CATALOG_ACCOUNT_CAP=8` with `ORCHESTRATOR_CATALOG_LIMIT=12`, and the sorted fill took 8 `nvidia_nim` routes and 4 `nvidia_nim_sub` routes before any `openrouter` route was reached, so a review that admitted 62 free routes across three accounts served a NVIDIA-only catalog (`noema-review` run 33969842312: `free_pool_admitted_routes` 62, `free_selected_count` 12, runtime preflight `ready_count` 2 of 12) and the failover loop had no other account to leave a stalled NVIDIA endpoint for -- the `noema-review` 502 class tracked in contextual-orchestrator#1045. Tier order (free before priced, ZDR before non-ZDR), the account cap, the limit, and the discovery-order independence contract are unchanged; the same input now yields 4 + 4 + 4. Contrasts with #1476, which hardens `_routable_discovered_models` against a pin that regresses the OpenRouter `evidence_only` flag: on the current pin (`2e414d15`, includes contextual-orchestrator#949) OpenRouter rows already reach the catalog builder, and the selection was what dropped them.

### Scheduler holds pre-review branch updates while checks are in flight

- `inspect_pr` now decides `wait` instead of `update_branch` when a behind, unreviewed head still has queued or running check runs (`has_in_flight_check_runs`, built on the existing `latest_check_runs`/`running_check_state`). Under a saturated runner queue each PR's own delayed `pull_request_target` scheduler run merged `main` into the head before review dispatch, cancelling every queued check on the old head (22/28 on #1926, 21/30 on #1484) and requeueing the PR at the back, so no head ever completed its checks: 76 of the 77 PRs merged into this repository since 2026-09-04 had 0/12 required contexts satisfied at merge time. The hold has no age cap on purpose -- a check that never finishes keeps the head in place instead of restarting that loop, and the update resumes once every newest check run is terminal. `CLAUDE.md` now describes both update paths. Tracked in #1935.

### CodeQL scan dispatch matrix serialisation

- Serialised the dispatched CodeQL matrix with `toJSON()` in `codeql-scan-dispatch.yml`. `codeql-pr.yml` sends `client_payload.matrix` as an array and the handler assigned it straight into `env:`, where a value must be a scalar, so GitHub rejected the step with "A sequence was not expected" and the dispatched scan never ran -- 0 successes against 136 failures since the handler was added in #1776. The validate step already consumes the value through `jq`, so JSON text is the shape it was written for and no consumer changes. Added a string contract test, because neither `yaml.safe_load` nor `actionlint` 1.7.12 flags this: it is an Actions template rule, so only GitHub's own validator rejects it and no local gate catches the class.

### Contextual-orchestrator pin refresh

- Advanced the central sidecar's default immutable CO revision to protected `main@2e414d15ba58f28597751b625a8a2f00fc9fadcf`, carrying current provider discovery, `orchestrator/free` workflow budget, web-search gateway, OpenCode Go, OpenRouter composition, and CI fixes into Strix, OpenCode, and Noema. The shared ModelClient default-timeout removal remains pending in contextual-orchestrator PR #1053. All callers still consume an exact SHA; no branch or tag is introduced.

### Scheduler target admission

- Added `ContextualWisdomLab/governance-risk-compliance` to the `OPENCODE_REPOSITORY_DISPATCH_TARGETS` repository variable directly (the actual source of truth for `ALLOWED_TARGET_REPOSITORIES` in both scheduler workflows) and removed the temporary hardcoded-literal bridge a prior commit had added to `pr-review-merge-scheduler.yml`/`pr-review-fix-scheduler.yml` to work around the variable not yet including it. Hardcoding a specific product repository into these shared scheduler workflows violates this repo's own thin-caller convention (`CLAUDE.md`: "Product hourly callers stay thin. Do not hard-code OriginWeave, aFIPC, naruon, or Keyverse into `pr-review-fix-scheduler.yml`") and broke `test_no_target_repository_is_hard_coded_in_the_shared_scheduler`. Updating the variable achieves the same admission with no code change and no test regression.

### Hourly review-repair queue-scan bound

- Raised `hourly-review-repair.yml`'s discovery ceiling from 50 to 200 while rotating deterministic 50-PR deep-inspection windows by hourly run number. The scheduler hydrates only the selected window and stops immediately after its single dispatch, preserving access to newer PRs without quadrupling expensive review/check/comment work. See `docs/doctoring/hourly-review-repair-single-file-consolidation.md`'s 2026-09-03 follow-up.

## [Unreleased]
- **Define an evidence-backed repository README quality standard.** Added `docs/repository-readme-quality-standard.md` as the shared review contract for product-first structure, code-current onboarding, authority boundaries, durable quality signals, and repository/source/dependency license due diligence. Product repositories continue to own their own README prose; the standard is linked from the root documentation map and does not centralize or generate product claims.
- Include merge-scheduler entrypoint, core, and regression-test changes in
  the existing runtime-quality workflow's trigger and suite selector. Scheduler
  workflow edits retain queue checks and also select the full review-repair
  suite. Selector-only test edits use the existing unconditional contract step;
  changelog-only edits still do not start this runner. No job is added.
- Complete the scheduler test isolation introduced by #1896 for the two
  remaining fixtures that invoke `inspect_pr(..., dry_run=False)` or
  `main(...)`. Both now stub the environment-gated startup-failure recovery
  owner, so `GITHUB_ACTIONS=true` exercises the production guard without
  issuing real GitHub calls or rejecting synthetic fixture SHAs.
- **Fix current-main contract drift that blocked the unscoped
  `agent-review-runtime-quality-ci.yml` "Verify scheduler and
  contextual-orchestrator review-repair contracts" step (which discovers and
  runs the full `tests/` directory with no positional arguments).** First,
  `strix.yml`'s `changed-scope` job had drifted from its byte-identical
  siblings in `security-scan.yml`/`sast-semgrep.yml`: PR #1869's
  `converted_to_draft` generalization folded its `if:` condition onto a
  multi-line `>-` block scalar, and the extra continuation lines survived
  `test_gate_job_is_byte_identical_across_the_five_workflows_apart_from_if`'s
  `if:`-line-only normalization. Collapsed it back to one physical `if:` line
  with the same expression -- no semantic change. Second,
  `test_noema_close_cleanup_selects_only_the_closed_pr_across_shared_display_titles`
  still looked up a step named "...for the closed pull request" and passed
  `CLOSED_PR_NUMBER`, both retired by the same PR #1869 when it generalized
  `noema-review.yml`'s `cancel-closed-pr-runs` cleanup step to "...for the
  inactive pull request" (env renamed to `INACTIVE_PR_NUMBER`/
  `INACTIVE_PR_HEAD_SHA`/`PR_ACTION`) and added a `live_target_matches`
  live-PR re-verification before every cancellation pass (mirroring
  `strix.yml`'s identical job) -- `tests/test_noema_review_gate.py`'s
  equivalent tests were already updated for this at the time, but this one
  was missed. Updated the test to the current step name and env vars and
  taught its fake `gh` to answer the new `pulls/<number>` live-state lookup;
  the PR #1507 "sibling Noema runs evade cancellation" `pull_requests[]`
  matching invariant it protects is unchanged and still correctly
  implemented in production. Third,
  `test_dispatch_strix_reruns_scan_job_not_sibling_publisher` only mocked
  `rerun_actions_job`, so in any environment with a real `gh` CLI on `PATH`
  its `dispatch_strix_evidence` call still ran the genuine
  `live_dispatch_head_matches` re-read, which invoked the unmocked `fetch_pr`
  against the real GitHub API for a synthetic PR that does not exist there --
  returning a live/head mismatch and `"stale_head"` instead of the expected
  `"rerun"` (and, absent `gh` entirely, failing even earlier with a missing
  executable). Added `monkeypatch.setattr(sched, "fetch_pr", lambda *_args:
  [pr])` alongside the existing `rerun_actions_job` mock so the live-head
  check observes the same fixture `pr` as authoritative, matching how every
  other call in this test path is already isolated from real GitHub state.
  Fourth, the Strix shell contract still expected job-level concurrency after
  PR #1878 moved same-PR coalescing to workflow admission; it now asserts the
  admission-level key and rejects the obsolete delayed key. Fifth, the
  consolidated review-recovery fixtures now use the 17 daily UTC schedules
  adopted by main instead of the retired hourly expressions.
- Remove the central `org-queue-sweep` runner and its organization-wide
  repository walk. Native PR/review events, auto-merge, trigger-aware
  same-PR cancellation, and each repository's daily `scan-pr-queue` recovery
  remain the bounded queue owners.
- Move Noema's repository-and-PR concurrency group to workflow admission so a
  new HEAD cancels its stale queued run before either consumes a job slot.
- Scope the current-head coalescer's workflow admission to repository and PR,
  while retaining exact-HEAD revalidation inside the trusted job.
- Align current-main workflow contract tests with native auto-merge completion,
  validated dispatch concurrency keys, rotating queue pagination, globbed watch
  paths, admission jobs, and the reviewed OpenCode dispatch blob.
- Restore the central Strix runtime after OpenAI Python 2.54.0 began importing
  HTTPX2 by selecting the SDK's `httpx2` extra in the hash-compiled dependency
  input. The required workflow now installs a verified HTTPX2 wheel before the
  scanner starts instead of failing before analysis with a missing module.
- Move the exact-artifact SBOM attestation quality contract into the existing
  agent review runtime selector and job, preserving Python 3.10 compilation,
  Python 3.14 test evidence, exact-head checkout, hash locks, and read-only
  permissions while removing the standalone workflow.
- Move the organization commercial-readiness contract suite into the existing
  agent review runtime quality selector and job, removing its standalone thin
  caller while retaining the reusable exact-head coverage implementation.
- Consolidate the standalone review-repair contract workflow into the existing
  agent review runtime quality selector and job. Matching PRs now reuse one
  checkout and dependency bootstrap while retaining the focused coverage,
  docstring, compile, and exact-PR concurrency contracts.
- Remove repository-wide Actions-run inventory and cancellation from the daily organization PR recovery sweep. Native per-PR concurrency and the local exact-head coalescer remain the cancellation owners; the sweep now spends its API budget only on missed review, merge, and branch-update recovery.
- Retire the standalone OSV and Scorecard pull-request workflows after both scanners moved into the required `security-scan.yml`. The organization ruleset now has seven required workflow paths, and `.github` branch protection no longer requires the duplicate `osv-scan / osv-scan` context.

- Add `.github/actions/orchestrator-free-sidecar`, an immutable composite-action boundary that checks out the exact central control-plane revision selected by `github.action_ref` and provisions the contextual-orchestrator `orchestrator/free` gateway. Provider bootstrap remains inside the central sidecar; callers receive only the gateway URL/token-file contract for the subsequent Agent step.
- Repointed 10 `scripts/ci/test_strix_quick_gate.sh` self-test assertions that had gone stale after the `pr_review_merge_scheduler.py`/`pr_review_merge_scheduler_core.py` facade/core split (#1803): they checked the now-98-line facade file for content (the exact-head branch-update guard, the squash-fallback retry, the subprocess-safety flags, the same-head Strix/OpenCode dispatch markers, and the `pr_head_ref` repository-dispatch payload) that lives in the core module instead, so they had been silently failing on every run since the split. The same repair aligns the wake-workflow list and daily recovery assertions with the current event-driven scheduler contract. A coverage/docstring version of the same gap was already fixed via #1810; this bash contract script was missed.
- **Fix the `coalesce` required check crashing instead of exiting cleanly for a superseded queued run.** `current-head-run-coalescer.yml`'s own design comment documents that `current_head_run_coalescer.py` raising `CoalescingRefused` (its remembered head no longer matching the PR's live head) is "a safe no-op" — but `main()` only ever called `coalesce()` directly, so the exception raised by `coalesce()`'s own top-level live-PR-state check propagated uncaught and crashed the job with exit code 1, instead of the intended graceful no-op. Reproduced live on `ContextualWisdomLab/.github#1503` (run `33766056421`, job `100684095620`): a stale queued run drained from the org-wide Actions capacity backlog against an already-superseded head failed the required `coalesce` check with `CoalescingRefused: pull request head moved before duplicate classification`. `main()` now catches `CoalescingRefused` specifically and exits 0 with an informational message; any other exception (malformed identity, an unavailable GitHub API) still fails closed.
## 2026-09-02 — Noema single-request gateway ownership

- Removed the repository-owned 900-second repair deadline and duplicate model repair call from Noema. The GitHub Actions caller now issues one structured-output request while `contextual-orchestrator` owns repair/failover/timeouts.
- Hardened serving-model telemetry against control-character/workflow-command injection and lone-surrogate encoding failures, restored actionable exact changed-line diagnostics, and constrained local trailing-comma repair to complete JSON values.
- Added permanent single-request/no-fixed-timeout regressions and retired obsolete deadline/retry fixtures.
- Documented the RCA boundary for the historical Noema 900-second repair deadline and distinguished it from the three 900-second sandboxed test-command limits in `opencode-review-dispatch.yml`; future telemetry must retain phase and failure class for request-too-large, discovery, rate-limit, provider transport, malformed-output, stale-head, and sandbox-command failures.

# Changelog

- **Consolidate current-head queue coalescing into the merge scheduler.** The standalone `Current Head Run Coalescer` duplicated one runner admission for every central pull-request event. Its exact-head worker now runs inside the already-required merge-scheduler job after immutable trusted-source materialization, preserving fail-closed PR/head/base revalidation while deleting the redundant workflow job.

All notable changes to the organization automation repository are documented in
this file. The format follows Keep a Changelog, and versioned releases follow
Semantic Versioning where the repository publishes a release.

## [Unreleased]
- **Stop Draft PR pushes from consuming five required-workflow runner lanes.**
  The first heavy job in Runtime Quality, CodeQL, Security Scan, Python
  Security, and SAST now skips while a pull request is Draft. Existing
  `ready_for_review` triggers create fresh exact-head evidence after review
  admission; push, schedule, and repository-dispatch coverage remains intact.
  A contract pins both pull-request-only and mixed-event guards.
- **Pin `opencode-review-dispatch.yml` off the starved floating `ubuntu-latest` image.**
  The 2026-09-01 floating-image fix (see that entry below) pinned `strix.yml`,
  `opencode-review.yml`, and `noema-review.yml` -- the three required-check
  gates -- to explicit `ubuntu-24.04`, and explicitly flagged "any remaining
  unpinned central workflows" as an open follow-up. `opencode-review-dispatch.yml`
  is the workflow the required `opencode-review` check's own `repository_dispatch`
  lands on to actually run the OpenCode CLI and post the exact-head verdict; all
  4 of its jobs still requested the floating image, so a starved runner here
  queues the real review work for hours just as surely as on the required check
  itself. Confirmed live on `contextual-orchestrator#1017`: its dispatch run
  (`33916313804`) sat `queued` with no runner assigned from creation, and a
  30-run sample of recent `opencode-review-dispatch.yml` runs org-wide showed
  14 still `queued` (several 10+ hours old) and 0 clean successes. Pinned all 4
  occurrences to `ubuntu-24.04`, matching the established pattern exactly, and
  extended `tests/test_required_review_runner_image_contract.py` (already
  refactored to a shared `assert_explicit_supported_image` helper by concurrent
  work) with a fourth case for this file.
- **Catch scheduler target-list drift before it silently fails an hourly heartbeat.** `hourly-review-repair.yml`'s per-cron `target_repository` matrix and the `OPENCODE_REPOSITORY_DISPATCH_TARGETS` repository variable (which gates `ALLOWED_TARGET_REPOSITORIES` in `pr-review-merge-scheduler.yml`/`pr-review-fix-scheduler.yml`) are two independently hand-maintained lists with no structural link -- three repositories (`governance-risk-compliance`, `nonnest2`, `quarantine-sandbox-runtime`) were added to the hourly matrix without a corresponding variable update, so their hourly heartbeat failed closed with "target repository is not allowlisted" until each was found and fixed the same day. Added `scripts/ci/opencode_repository_dispatch_targets.json`, a hand-maintained mirror of the variable's live value, and a new contract test (`test_every_hourly_caller_target_is_in_the_dispatch_targets_mirror`) asserting every hourly-caller target is present in it, so a future PR that repeats the omission fails at review time instead of at the next silent hourly failure. See `docs/doctoring/scheduler-target-list-drift-20260902.md`.
- **Fix a stale `test_strix_quick_gate.sh` assertion left broken by the `#1630`
  scheduler-cadence lengthening.** `pr-review-merge-scheduler.yml`'s repository-local
  heartbeat was changed from a quarter-hourly `cron: "*/30 * * * *"` to an hourly
  `cron: "30 * * * *"` (see `docs/doctoring/actions-queue-saturation-hourly-sweep.md`),
  and the Python regression `tests/test_actions_queue_saturation_scheduler_cadence.py`
  was updated to match at the time — but the parallel bash contract in
  `scripts/ci/test_strix_quick_gate.sh` still asserted the literal old string, so
  every PR whose required `exact-head-path-policy` check ran this script against a
  current `main` checkout failed on an assertion the workflow file itself could no
  longer satisfy, regardless of the PR's own diff. Updated the assertion to the
  current cron string and corrected an adjacent stale "15-minute organization sweep
  / 30-minute scheduled scan" description to the current hourly/hourly cadence.
  Verified: `bash scripts/ci/test_strix_quick_gate.sh` now passes against unmodified
  `main` (confirmed failing before this fix, on the same clean clone); full suite
  unaffected (2600+ passed, 100% coverage, 100% docstrings) since this is a
  bash-only assertion string with no Python-side counterpart to update.
- **Consolidate the two genuinely duplicate quality-CI callers behind one reusable
  `workflow_call` gate; leave the other six alone.** An audit of the 8
  `.github/workflows/*-quality-ci.yml` bootstrap-templated files found only one pair —
  `javascript-coverage-quality-ci.yml` and
  `organization-commercial-readiness-loop-quality-ci.yml` — where the shared skeleton
  (checkout at the exact PR head, an identical pinned six-package mini-requirements
  heredoc, `coverage run --branch -m pytest --import-mode=importlib`, `coverage report
  --fail-under=100`, `compileall`, `git diff --exit-code`) was byte-for-byte the same
  logic with only the timeout, pytest target, and coverage `--include` path varying per
  subsystem. Extracted that shared shape into a new
  `.github/workflows/exact-head-coverage-quality-gate.yml` reusable workflow
  (`workflow_call`-only, four required inputs: `timeout_minutes`, `pytest_target`,
  `coverage_include`, `compileall_targets`) and turned both callers into thin
  `uses:`/`with:` wrappers. Verified first that no branch-protection required status
  check or the org's required-workflow ruleset references either caller's job name
  (`exact-head-coverage-contract` / `exact-head-policy`) before restructuring, so nothing
  downstream depends on their exact shape. Updated the three contract tests that pinned
  the old inline text
  (`test_organization_commercial_readiness_loop_policy.py`,
  `test_organization_commercial_readiness_loop_import_contract.py`) to check the
  coverage/exact-head mechanics against the shared gate file and the subsystem wiring
  against each caller, and added
  `tests/test_exact_head_coverage_quality_gate_contract.py` to pin the gate's own
  `workflow_call` contract and both callers' input wiring. The other 6 files
  (`agent-mention-router-quality-ci.yml`, `exact-artifact-sbom-attestation-quality.yml`,
  `noema-token-lifetime-quality-ci.yml`,
  `opencode-rust-coverage-toolchain-quality-ci.yml`, `strix-changed-path-quality-ci.yml`,
  `trusted-uv-materializer-quality-ci.yml`) look superficially similar but each encodes a
  genuinely different policy -- harden-runner presence, a docstring/interrogate gate,
  exact-head-verification mechanics (or, for noema, no `ref:` pin at all), multi-Python-
  version matrices with non-shared extra logic (a tomli-fallback exercise, a Python 3.10
  compile-only contract), or no `…17557 tokens truncated…nvidia_nim_sub`/`openai`, and fixes the actual root cause — `_fetch_json`
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

- Prefer the job-scoped `github.token` when the central OpenCode dispatch
  publishes a commit status back to the same `.github` repository. The job's
  declared `statuses: write` permission now reaches the endpoint instead of an
  unrelated OpenCode App installation token that can lack commit-status write
  permission; cross-repository status publication keeps the existing explicit
  PAT/App credential chain.
- Keep the central required-workflow coverage placeholder from superseding a
  failed repository-dispatch coverage run; coverage retry and merge decisions
  now use authoritative execution evidence for the central scheduler.
- Re-dispatch an exact-head OpenCode review after its coverage-only blocker is
  cleared, selecting the newest coverage rerun by timestamp across workflow
  names and ignoring only the superseded `opencode-review` failure and central
  required-workflow placeholder. Conflicting heads and failed sibling jobs in an
  OpenCode workflow remain fail-closed alongside unresolved threads, Strix,
  coverage, and unrelated failed checks.
- Stop the organization PR sweep after the first exhausted shared GitHub App
  installation bucket, rather than repeating up to three reset-aware waits and
  follow-on queue-hygiene reads for every remaining repository. The current
  target is recorded as deferred, the run remains non-fatal for this external
  capacity condition, and later rotations retry the unfinished repository set.
- Close a gap in the above deferral: a shared-installation rate limit hit
  mid-scan (inside a single PR's `inspect_pr()` call — an active-run read,
  cancellation, dispatch, merge, or branch update — rather than the
  once-per-repository `fetch_open_prs()`/`fetch_pr()` call before the loop)
  previously fell back to an ordinary `action_error` decision and kept
  scanning the repository's remaining PRs with the same exhausted bucket,
  and returned exit 0, so the workflow's "API rate limit exceeded"
  skip-and-defer branch — which only triggers on a non-zero sweep exit —
  never saw it and later repositories in the same rotation kept spending
  the bucket too. It now stops the repository's scan and propagates the
  error like the pre-loop path already did.
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
