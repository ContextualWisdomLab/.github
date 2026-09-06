# CI failure-signature triage

**Audience:** any agent (Claude, Codex, Grok, Gemini) looking at a red required check in
`ContextualWisdomLab/.github`, `ContextualWisdomLab/noema`, or
`ContextualWisdomLab/contextual-orchestrator` and deciding what to do in the next minute.

**How to use it:** string-match the error you are looking at against a heading below, then follow
that section's **Do** / **Do not**. Every mechanism claim here was verified against the code on
`origin/main` before being written down; the file:line citations are the evidence, not decoration.
If a section's cited line no longer says what this document claims, the section is stale — fix it
here rather than working around it in a consuming repository.

**Scope:** this is a *signature → action* catalog. Incident retrospectives and repair evidence live
in their own records, e.g.
[`noema-review-failure-retrospective-and-improvement-plan-20260903.md`](noema-review-failure-retrospective-and-improvement-plan-20260903.md),
[`startup-failure-and-strix-concurrency-20260904.md`](startup-failure-and-strix-concurrency-20260904.md),
and [`actions-queue-saturation-hourly-sweep.md`](actions-queue-saturation-hourly-sweep.md).

Baseline for every claim below: `.github` `main@7fcada597`, `contextual-orchestrator` `main@a080297d`,
`noema` `main@e1ac9d5`, all as of 2026-09-05.

**One entry here has already been wrong.** Signature 2 originally told you to re-run the failed job;
a reviewer challenged the premise, and checking it against real run data showed a re-run cannot help,
because `workflow_sha` is bound at run creation. Following the retracted advice would have produced
an unbounded re-run loop feeding the very queue saturation described in signature 7. The entry now
carries the correction and its evidence limits. Treat that as the standard this file is held to: a
plausible mechanism is not a verified one, and an entry that survives a serious attempt to refute it
is worth more than one that reads well.

**Before acting on any PR: ownership is decided by the PR body, not by commit trailers.** A branch
can carry your session's `Claude-Session:` trailer on several commits and still not be yours to drive,
because the repository owner may have taken it over since. The test is the body: a section headed
`Current exact authority — <date> KST` (or `Current exact evidence` / `Current authority`) listing
exact head and base SHAs and exact check-run ids, plus an explicit merge-discipline list ("Keep
Draft until …", "Do not … self-approve, force-push …"), means the owner is hand-driving it with
exact-head discipline and no agent edits it, pushes to it, or resolves its threads. Measured
2026-09-05 on `noema`: a fingerprint search returned three "my" PRs (#535, #539, #540); all three
bodies carried that section, two were being driven through a different app entirely, and the one
with two of this session's commits on it was nonetheless not this session's to touch. Searching by
fingerprint finds *history*; only the body tells you *authority*. (#933 earlier the same day was the
failure mode this prevents: an agent merged into a lane the body had explicitly reserved.)

---

## 0. Before anything else: your local checkout is probably stale

**Symptom.** None — that is the problem. Everything looks normal and your conclusions are wrong.

**Mechanism.** Long-running agent sessions keep a working tree that was cloned once. `main` in this
organization advances roughly every 20 minutes. Measured 2026-09-05: `/home/user/.github` was **218
commits behind** `origin/main` (`docs/product-technical-gap-baseline.md` 2615 lines locally vs 3234
on main), and `/home/user/contextual-orchestrator` still showed `nim_benchmark.py` `valid_until_date`
`2026-09-04` when main already carried `2026-10-05`. Reasoning from that tree re-derives bugs that
are already fixed, and quoting its line numbers cites lines that do not exist on main.

**Do.** At every wake, and before reading any file you intend to reason about or edit:

```bash
git fetch origin main && git rev-list --count HEAD..origin/main
```

If the count is greater than zero, treat the working tree as **not evidence**. Read target files as
`git show origin/main:<path>`, or work in a fresh `git worktree add <dir> origin/main`. Never quote a
line number you did not read from `origin/main`.

**Do not.** Do not report a finding, open a PR, or file a gap entry whose evidence came only from an
unverified working tree.

---

## 1. `opencode-review` fails with "No APPROVED or CHANGES_REQUESTED from opencode-agent on the current head"

**Symptom.** The required `opencode-review` check is red with exactly:
`No APPROVED or CHANGES_REQUESTED from opencode-agent on the current head. The dispatch workflow will
rerun this failed job after publishing an authenticated exact-head verdict.`
(`.github/workflows/opencode-review.yml:488`).

**Mechanism.** This is a designed fail-closed wait, not a defect in the PR's code. The same job first
fires a `repository_dispatch` carrying `required_run_id: $GITHUB_RUN_ID`
(`.github/workflows/opencode-review.yml:409`), then fails so it releases its runner instead of
polling. Later, `.github/workflows/opencode-review-dispatch.yml`'s "Wake exact-head required OpenCode
workflow" step (line 7532) calls `POST /actions/runs/{id}/rerun-failed-jobs` (line 7572) on that
exact run.

**Do.** Check whether a newer `OpenCode Review Dispatch` run for this head is in flight; if yes, wait.
If none is, treat it as a real stall and inspect that run for: receipt-gate rejection
(`scripts/ci/opencode_review_receipt_gate.py:136` rejects fallback and model-unavailable approvals), a
missing `PR_REVIEW_MERGE_TOKEN` / `OPENCODE_APPROVE_TOKEN` wake credential
(`opencode-review-dispatch.yml:7549`), or a verdict published under a non-`opencode-agent` identity.

**A distinct sub-cause where waiting is useless: the dispatch run exists and is rejected at its
first gate.** `.github/workflows/opencode-review-dispatch.yml:126-131` authorizes a
`repository_dispatch` only when *both* `github.triggering_actor` and `github.event.sender.login`
equal the single value of `vars.OPENCODE_REPOSITORY_DISPATCH_ACTOR`. Since #1497 (2026-08-31),
`opencode-review.yml:431` sends that dispatch through the OpenCode GitHub App token, so the sender
is `opencode-agent[bot]`; if the variable still names `github-actions[bot]`, every such run dies in
`validate-pr-metadata` at "Bind workflow inputs to live organization pull request metadata" and no
verdict can ever be published for any head (#1929). Discriminator: open the newest dispatch run for
your head — if its **first** job concluded `failure` with `::error::repository_dispatch
authorization rejected actor=…`, you are in this case, and no amount of waiting or re-running the
required job changes it. Remedy is #1932 (a comma-separated allowlist, mechanism only) plus an owner
updating the variable; neither is a per-PR action. The same variable gates
`codeql-scan-dispatch.yml:142`, and the sibling repositories re-dispatch after each rejection, so the
flood is visible from any repository's queue: 01:30–04:30Z on 2026-09-06, 231 `CodeQL Scan Dispatch`
runs, two or three per SHA, every one rejected in 3–6 s after ≈65 minutes of queue (signature 7).

**Do not.** Do not reflexively re-run the failed job by hand, and do not "fix" the PR's code — this
failure says nothing about it.

**What the one handler that passed the gate did, 2026-09-06T01:34Z.** `.github` #1492's handler run
`33991725331` was dispatched by the *scheduler* path (`github-actions[bot]`, 21:00:01Z, so it passed
`validate-pr-metadata`), then queued stage by stage — `validate-pr-metadata` 22:18Z,
`coverage-source-tree` 23:15Z, `coverage-evidence` 00:30Z, `opencode-review` 01:26Z (signature 7: each
`needs:` stage re-enters the queue) — and its review reported `Model pool: exhausted` and fell back to
deterministic evidence, which returned `REQUEST_CHANGES` because a stale cancelled Strix check sat on
the head. So fixing the dispatcher variable (#1929) reopens the *path*; the verdict at the end of it
still runs into signature 3's pool, and the model-unavailable fallback can only approve a head whose
peer checks are already complete and clean. Expect the first post-fix verdicts to be
`REQUEST_CHANGES` on heads carrying any stale red check, not approvals.

---

## 2. `strix` fails within seconds with `AttributeError: ... no attribute 'asyncio'` or `ModuleNotFoundError: No module named 'httpx2'`

**Symptom.** The required `strix` check dies in 0–2s: a traceback ending in
`AttributeError: 'function' object has no attribute 'asyncio'` **or**
`ModuleNotFoundError: No module named 'httpx2'`, then
`Strix run failed for model 'orchestrator/free' after Ns (exit code 1)`.

**Why the pin exists — read this before "repairing" it.** `.github/workflows/strix.yml:398-400`
resolves `trusted_ref` from `job.workflow_sha`, and line 428 checks the entire trusted Strix source
tree out of `ContextualWisdomLab/.github` at exactly that SHA. That pin **is** the
`pull_request_target` trust boundary — it is what stops a pull request from supplying the review
scripts that judge it, and `CLAUDE.md` states the rule directly ("The required review workflows run
the *base branch's* trusted scripts"). The staleness described below is a consequence of that
control, not a defect in it. Do not "fix" it by pointing `trusted_ref` at `main`, at the PR head, or
at any floating ref: that converts a supply-chain control into a supply-chain hole, in a workflow
that runs with elevated permissions against every repository in the organization. The fallback to
the literal string `"main"` at lines 405-409 is dead code in practice — `workflow_sha` is always
populated — and it must stay unreachable.

**Mechanism.** `workflow_sha` is bound when the **run** is created and is never re-resolved
afterwards. For a `pull_request_target` run it equals `github.sha`, which is the *base branch* tip —
not the PR head, which the run reports separately as `head_sha`. A run that sits queued for hours
therefore executes against base source as of hours ago. Measured on run `33863887675`: created
`10:34:35Z`, the trusted checkout resolved at `15:35:15Z` — five hours later — and fetched
`b15cb994`, which was main's tip at `10:31:52Z`. In the interval main advanced roughly twenty
commits, **including `769691526` (#1851), the very Strix fix that would have made the job pass**; the
job nevertheless failed at `15:50Z` against pre-fix source. The two error strings are two staleness
windows: `AttributeError` means the pin predates `87352d98` (#1783), the `httpx2` import error means
it predates `769691526` (#1851).

**Do.** First confirm on current main that `scripts/ci/strix_timeout_compat.py` resolves the
submodule via `sys.modules["strix.interface.main"]` and that `requirements-strix-ci-hashes.txt` pins
`httpx2==2.12.0`. Then cause a genuinely **new run**, in that order — the fix must already be on main
*before* the new run is created, because the new run pins itself at *its* creation time. The one
remediation that is both effective and permitted here is to **merge current main into the PR head and
push**: that is a real commit, it makes the branch mergeable anyway, and the resulting
`pull_request_target` run pins to a main that carries the fix.

**Do not.** **Do not re-run the failed job.** A re-run reuses the same `run_id` and therefore the
same `workflow_sha`; GitHub's own documentation states a re-run "will also use the same `GITHUB_SHA`
(commit SHA) and `GITHUB_REF` (git ref) of the original event", and GitHub staff have confirmed a
re-run "will use the original workflow file". So a re-run re-resolves `trusted_ref` to the identical
stale SHA and reproduces the identical failure — indefinitely, while each attempt consumes a slot in
a queue that is already ~456 deep against ~3 executing (signature 7). This document previously said
the opposite; that instruction was wrong and is retracted. Do not push an empty commit and do not
close and reopen the PR to force a new run either — both are forbidden by the organization's merge
discipline, and the merge-main-in step above already produces the new run legitimately. Do not patch
the consuming repository: its head SHA is not implicated.

**Evidence limits.** The attempt-to-attempt comparison that would settle this most directly does not
exist in this organization's retained history: across 1,110 scanned run records exactly one Strix run
had `run_attempt > 1` (`33926114577`), and both of its attempts were cancelled before the `strix` job
started, so their logs return HTTP 404. The conclusion above rests on creation-time pinning observed
directly in two real runs (`33863887675`, `33860232589`) plus GitHub's documented re-run semantics —
not on a same-run log diff. A `workflow_dispatch` run should also resolve `workflow_sha` freshly, but
that is inferred from `repository_dispatch` behaviour and the general creation-time rule; no
`workflow_dispatch` Strix run appears in the sample.

---

## 3. `noema-review` fails after ~30 minutes with `HTTP Error 502: Bad Gateway` and `caller attempts=1`

**Symptom.** One job-log line:
`Noema gateway transport failed: HTTPError: HTTP Error 502: Bad Gateway; caller attempts=1,
duration=1814.3s, phase=response_error, served_model=<id>` — observed durations 1800–2300s, on
`contextual-orchestrator` #1012 and #1043.

**Mechanism.** Gateway-side, not the diff. `scripts/ci/noema_review_gate.py:1507-1674` sends exactly
one request with no retry loop, called once from `.github/actions/noema-review/two_phase.py:170`. The
gateway is a `127.0.0.1` sidecar vendored from the pinned SHA in
`scripts/ci/contextual_orchestrator_review_sidecar.sh:17` — never the PR head. A client-visible 502 is
raised only after `contextual_orchestrator/orchestrator.py:7774-7896` exhausted every candidate;
content-shaped rejections would surface as 400/413
(`contextual_orchestrator/provider_errors.py:67-92`).

**Do.** Re-run the failed `noema-review` job by hand. **Nothing re-runs it automatically** —
`scripts/ci/pr_review_merge_scheduler_core.py:3746` re-runs Strix only, and
`scripts/ci/noema_review_handoff.py`'s dispatch requires a reusable exact-head OpenCode approval.

**Measured 2026-09-05 (10:00–16:25Z), which qualifies the "re-run" above.** Of 14 completed,
non-cancelled `noema-review` runs in `.github`, 7 succeeded and 7 failed, six of them this 502 after
180–2174 s of held runner (about 57 minutes of slot for zero verdicts). The policy report of a failing
job listed 12 probed routes, all `nvidia_nim` / `nvidia_nim_sub` — one upstream — so the
failover loop cannot leave a stalled upstream whatever its retry budget (root cause and design
directions: `.github` #1903). The policy layer had admitted 62 free-pool routes across three accounts; the gap is the sidecar's own cap override — `scripts/ci/contextual_orchestrator_review_sidecar.sh:43` exports `ORCHESTRATOR_CATALOG_ACCOUNT_CAP` with a default of **8** while `policy.DEFAULT_ACCOUNT_CAP` is 4, and `build_zdr_prioritized_catalog` fills its 12-route limit in `(cost, zdr, provider, model)` order, so alphabetically `nvidia_nim` takes 8, `nvidia_nim_sub` takes 4, and `openrouter` is never reached (peer-refuted 2026-09-05: an earlier version of this entry blamed the launcher's `evidence_only` strip, which does not fire on the current pin — CO#949 is vendored). `.github` #1476 is the hardening for a regressed pin, not today's lever; the lever is a fill that round-robins across accounts within a tier — `.github` #1939 (host 1 session), which keeps the sidecar's cap default and argues the cap no longer decides diversity once the fill interleaves. Same family as #1415 and #1921: an alphabetical tiebreak plus a budget starves whatever sorts last. #1382's original policy-layer `EVIDENCE_ONLY_PROVIDERS = {"openrouter"}` filter would recreate the single-upstream pool by another route; do not reintroduce it, and do not remove OpenRouter from `FREE_POOL_CREDENTIAL_NAMES`, without the routing-policy owner deciding. While the stall is measurably ongoing (failure rate near 50% over the
last hour), a re-run is a coin flip that costs another 3–36 minutes of a slot the queue is starving
for. Measure before re-running: list `noema-review.yml` runs from the last hour and grep the failed
jobs' logs for `HTTP Error 502`; re-run once the rate has dropped, not while it is high.

**Closed 2026-09-05T17:25Z: #1939 (round-robin catalog fill) is on `main`, owner-merged.** A head
whose Strix or Noema run failed on the stall before that does not recover by re-run: `workflow_sha`
is bound at run creation, so the re-run executes the pre-#1939 sidecar (signature 2's mechanism, now
on this signature's side of the line). The remedy for such a head is one push that merges `main` —
a new event binds the current sidecar — and it is worth doing even mid-batch, because the review that
would have been reset had already failed. Applied to four heads at 21:15–21:21Z, each after the full
local gate.

**Measured again 2026-09-05T22:20Z, after #1939: the fix closed the pool-diversity gap, not the 502
itself.** The first post-#1939 `noema-review` runs (created after 17:25Z, so bound to the new sidecar)
were 1 failure (`#1872`, run `33985079091`, 40 minutes of held runner) and one green job that was
not a verdict at all: `#1902`, run `33982955696`, was a draft skip (`PR is draft; Noema verdict
preparation skipped.`, verdict step 1 s). The first version of this paragraph counted it as a
success; the stage-level tally further down is the authoritative one. The failing run's policy report now lists `openrouter`, `nvidia_nim` and
`nvidia_nim_sub` routes as `ready` — the diversity #1939 promised — and still ended in
`HTTP Error 502 … duration=1989.9s, served_model=deepseek-ai/deepseek-v4-flash-0731`; `#1940`'s run
`33981136873` did the same over 3122 s. Host 1 traced the path from source twice and the first artifacts
settled it (`.github` #1938 thread, 01:28Z): the `attempt=1/1` lines in a trace are the **preflight
probes** (preflight client `max_retries=0`, twelve routes in about a minute); the serving phase for
the `orchestrator/free` virtual pool is `_invoke` — `tool_retry_attempts=1` on top of the client's
`max_retries=2`, so each agent gets two rounds of three attempts at the 90 s per-recv limit, measured
270.3–271.1 s per silent round and 541 s for one agent's two rounds — and an internal repair/judge
loop can re-enter `_invoke` and walk the same agents again inside one caller request. Two artifacts
show the shape. `.github` #1661's run `33995553859` (3873 s → 502): the same three agents walked
three times, 13 silent rounds of ≈270 s on the two NVIDIA deepseek-flash keys, `cohere/north-mini-code`
ending `provider_rejected_permanent`, and two preflight-ready routes (`nvidia_nim_sub` deepseek-pro,
`dots-3`) **never attempted**. `.github` #1946's run `33996197307` (artifact `9980320306`, 2539 s →
502): `nvidia_nim_sub` deepseek-v4-flash attempted 29 times and never answered (24 timeouts),
`provider_exhausted` nine times for that one route, its circuit opened twice (`failures=3.0
threshold=3 reset_seconds=30.0`) and was re-admitted within a minute each time because a 30 s reset
is shorter than one 90 s attempt, and the last call at 01:25:10 went to the same route and timed out
while two other ready routes had answered — about 36 of 43 minutes on a route that produced no byte.
A long duration therefore counts silent ≈270 s rounds, most of them re-admissions of the same one or
two agents; it does not count distinct routes, and the per-agent timestamps in the artifact are the
only direct measure. #1943 (sidecar `DEBUG` trace), #1944 (`noema-review`
uploads `strix_runs/contextual-orchestrator-sidecar.stderr.log` and the preflight report as the
`noema-sidecar-evidence` artifact on failure) and #1945 (the sanitizer admits the orchestrator's
`provider_attempt` / `provider_exhausted` / `circuit_*` lines), all on `main` by 22:15Z, turn that
into a per-route timeline you can read from the artifact instead of inferring. A second post-#1939
shape, 23:47Z: `.github` #1938's run `33992736660` ended after **551.0 s** with `HTTP Error 429: Too
Many Requests` and `served_model=deepseek-ai/deepseek-v4-pro-0813`. Do not read that as "one route,
no failover" — host 1 refuted exactly that reading from the pinned source within minutes: a 429 is
`retryable=True` (`provider_errors.py:82`), which `_invoke` turns into one same-agent retry and then
`FAILOVER_AGENT` to the next candidate (`orchestrator.py:7828-7868`, `tool_fallback.py:114-154`), and
the caller receives the *last* route's *last* error, so `served_model` names the last route tried,
never the first. What that run's preflight actually held: `ready 3 / rejected 9` — the three ready
routes were all NVIDIA `deepseek-v4` (`flash` on the sub account, `pro` on both accounts), and all four
`openrouter` routes were rejected at preflight with 429 (plus three NVIDIA 404s and one 529). So
`#1939`'s account interleave delivered the diversity and OpenRouter's rate limit took it away again
before the first request: the pool the failover walked was NVIDIA-only for a different reason than
before. There is no "routes walked" fingerprint: `duration / 270` approximates silent *rounds*, and
the artifacts above show the same agent taking most of them, so duration counts re-admissions of a
stalled route, not routes. Only the `noema-sidecar-evidence` artifact
(#1944; that run predates it, and a re-run keeps the same `workflow_sha`) gives the walked-candidate
list with the time each one held the request. Tally of post-#1939 `noema-review` runs in `.github` with a PR attached, by the
`Prepare Noema model verdict` step's own conclusion, at 02:10Z: **0 succeeded, 23 failed** (the
23rd being `#1938`'s sanctioned re-run, attempt 2, 3014 s → 502 — the measurement that keeps every
other held re-run held)
(verdict-step durations 199–4273 s, median ≈1500 s; among them `#1872` 502 after 1989.9 s, `#1938`
429 after 551 s, `#1930` 429 after 1444.7 s, `#1913` 502 after 2123.7 s, `#1916` 502 after 3783.4 s —
63 minutes of one or more candidates holding the request open). Pre-#1939 (10:00–16:25Z) the same
count was 7 of 14. Two earlier versions of this tally were wrong in two different ways: one counted
"4 succeeded"
because three run-level successes at 21:59–22:15Z were the closure-event runs of #1943/#1944/#1945
after merge, whose `noema-review` job was skipped before any step ran. A `pull_request_target` run
whose job skipped on "events without pull request context" reports `conclusion: success` at run
level; and the other counted `#1902`'s two green jobs as verdicts when they were draft skips — the
job log says `PR is draft; Noema verdict preparation skipped.` and the verdict step took 0–1 s. Count
jobs whose `Prepare Noema model verdict` step has a conclusion *and* a duration in minutes; never run
conclusions, never a green job whose verdict step finished in a second.

**Why the ready count fell from 5–6 to 1–3 across #1939, independent of load.** The 4+4+4 fill takes
each NVIDIA key's first four models in catalog order, which is alphabetical within the tier:
`deepseek-v4-flash`, `deepseek-v4-pro`, `gemma-3-12b`, `gemma-3-4b` — and the two `gemma-3` routes are
permanent 404s, so each key serves two working routes, both the most-contended deepseek models. The
pre-#1939 8+4 fill reached `meta/llama-3.2-11b`, `meta/llama-3.2-90b` and `meta/muse-glimmer-30b`, which
were *ready* in every pre-#1939 Strix artifact opened (runs `33979406293`, `33979153466`,
`33978435797`: ready 6, 6, 5 of 12 at 16:37–16:56Z); discovery still lists 21 models per NVIDIA key
that never reach the served set. Same family as #1415 / #1921 / #1939 — an alphabetical tiebreak plus a
budget starves whatever sorts last, and this time the budget is four per account with two dead routes
sorting first. The lever proposed on `.github` #1948 (host 1's lane) is a lazy per-account fill that
probes down the ranked list until K routes are ready, which also bounds probe spend.
The strongest evidence of what the 429 variant *is* came from `.github` #1930's `strix` failure in the
same window (run `33992904674`, 23:48–00:12Z), because the Strix workflow already ships the sidecar
files in `strix-reports`: preflight **ready 1 / rejected 11** of 12 selected routes — all four
`openrouter` 429, the primary NVIDIA `deepseek-v4-pro` and `v4-flash` 429, the sub-account `v4-flash`
a `TimeoutError`, the four `gemma-3` routes 404 — and the sole ready route (`nvidia_nim_sub`
`deepseek-v4-pro-0813`) answered `429 rate_limit_exceeded` on first contact and on all five of Strix's
replays (`run.json` `llm_usage.requests: 0`). `.github` #1938's Strix run `33992736699` forty minutes
later read `ready 3 / rejected 9`, got seven completions through, then hit the same persistent 429 and
stopped after 41.5 minutes; its sidecar stderr counted 36 × `status=429 rate_limit_exceeded` and
14 × `status=500 internal_error`. `.github` #1916's Strix run `33992902189` (artifact `9980773663`)
read `ready 4 / rejected 8` — all four deepseek-v4 routes — made 29 requests over **2 h 18 min**
while the gateway answered `status=500 code=internal_error` 76 times, and died on Strix's stream
idle timeout: a third shape (bulk gateway 500s) next to the 429 and the held-open 502, and the
single most expensive review job of the night. That is not a routing defect: the free pool had no capacity on any
account at that hour, and #1939's 4+4+4 interleave had nothing to interleave. Each
such job still holds a runner for ≈25 minutes before failing, in a queue hundreds deep. **Do not
re-run a 429-variant failure while the most recent artifact in the repository shows ≤1 ready route**:
the odds are near zero and the cost is the slot. The lever (a pool that rate-limits on first contact
should fail in seconds, not minutes, and an upstream that holds a request open needs a response-start
or total deadline at the gateway — the owner's call) lives in the orchestrator's passthrough policy
and in strix-agent's replay loop — the orchestrator lane's, and an owner decision on paid routes — not in this repo's
sidecar; the owner's tracking issue is `contextual-orchestrator#1045` (fix PR `contextual-orchestrator#1049`,
failover with typed attempt evidence), and the night's cost is posted there: 8 failed `noema-review`
/ `strix` jobs on runs created 21:00–00:18Z burned **184 runner-minutes** in a 230-deep queue, and
the three that completed in the next 25 minutes (`#1938` Strix 41.5, `#1916` Noema 63, `#1930` Strix
32) took the total past **290**. Two more pre-bump Strix jobs then ran to the shape's natural end: `#1271`
(`33995516908`) and `#1231` (`33994984527`) each held a runner for 4 h 15 m (preflight `ready 6 / 12`
at 00:2xZ; 206 and 202 gateway `status=500 code=internal_error` lines; #1271 issued 170 requests, 136
of them with usage, and ended `failed`) — about 510 runner-minutes for no verdict, the two most
expensive review jobs on record. So: a
base-merge push recovers a head from the
*pre-#1939* single-upstream stall, and it is still worth doing; it does not make the post-#1939 walk
shorter; and re-running a post-#1939 failure is the coin flip described above, at a cost the previous
run's duration does not predict. The remaining lever — the per-recv timeout and retry product
inside the gateway — lives in `contextual-orchestrator`, not in this repo's sidecar, and the
orchestrator lane holds it; do not add a caller-side deadline here (`noema_review_gate.py:1520`
states why the caller carries none).

**Closed again 2026-09-06T03:01Z: the retry-stacking loop itself is fixed on `main`.** The owner
bypass-merged `.github` `efb892692`, advancing the sidecar's `ORCHESTRATOR_PIN_SHA` from `2e414d15`
to `414f2297` — the commit that merges `contextual-orchestrator#1081`, whose fix stops `_invoke`'s
own retry-then-failover decision from stacking on top of the client's `max_retries` (reproduced on
the old pin as six real attempts per candidate, confirmed at ≤ 2 on the new one). The bypass was
necessary for the same reason as every sidecar pin bump: the PR's own required reviews run the base
branch's still-stale sidecar (`pull_request_target` trust boundary), so normal review would have hit
the bug being fixed. As with #1939, a head whose runs failed before the bump does not recover by
re-run — one base-merge push binds the new pin — and the pool condition (signature 3's rate-limited
free tier, `.github` #1948) is a separate lever that this bump does not touch.

**A fourth shape, fail-fast at provisioning (first seen 2026-09-06T04:24Z).** When preflight finds
*zero* ready routes the launcher exits before `/healthz`, `contextual_orchestrator_review_sidecar.sh`
reports `sidecar exited before healthz (status 1)`, and the job fails in ≈5 minutes at "Provision
contextual-orchestrator review sidecar"; "Prepare Noema model verdict" is *skipped*, and the
`noema-sidecar-evidence` artifact still uploads. `.github` #1913's run `34006939646` (artifact
`9982569956`; pre-bump pin, the run having been created 24 minutes before `efb892692`) read
`ready 0 / rejected 12`: both keys' `deepseek-v4-flash` 429, both keys' `deepseek-v4-pro` — until
then the route carrying reviews — `TimeoutError` at the 90 s probe bound, the four `gemma-3` 404,
all four OpenRouter free routes 429, bytez discovery `http_status_500`. Tally it apart from
verdict-step failures (a skipped verdict, not a failed one) and read it as the cheapest form of this
signature: five minutes of runner instead of thirty to seventy. The re-run rule above applies
unchanged — 0 ready is the strongest possible ≤1 reading — and the base-merge remedy is the same. It recurred on the new pin thirty minutes later — `.github` #1661's run `34008191123`
(artifact `9982909775`, sidecar at `414f2297`, 04:48–04:51Z) read the identical `ready 0 / rejected
12` — so the pin bump cannot be evaluated until the pool has at least one ready route: the first
post-bump tally line is a provisioning failure, not a verdict. Strix shows the same shape at its own step, "Provision
contextual-orchestrator Strix sidecar", in about nine minutes (`.github` #1938's run `34008403183`,
artifact `9983066996`, 05:05Z — the third consecutive 0 / 12 artifact); "Run Strix (quick)" is
skipped, and the `strix-reports` artifact carries the preflight and discovery evidence.

**A fifth shape — one ready route that cannot serve (first seen 2026-09-06T05:20Z, the first
post-#1081 serving-phase sample).** Route preflight passes with `ready 1`, "healthz and
provider-route preflight confirmed", and then the sidecar script's *gateway* preflight
(`contextual_orchestrator_review_sidecar.sh`, `REVIEW_PREFLIGHT_GATEWAY_MAX_ATTEMPTS=3`) cannot get
one completion through that route: each attempt is served with exactly two 90 s tries on the only
candidate (`1 + tool_retry_attempts`, no transport-retry stacking underneath — the post-#1081
arithmetic), ends `request_failed status=502 code=provider_connection_error`, and the job fails at
the provisioning step after 3 × 2 × 90 s ≈ 9 minutes of serving on top of the route walk. `.github`
#1946's run `34008655765` (artifact `9983259344`): `nvidia_nim_sub` `deepseek-v4-pro` answered the
16-token probe in 88 s, then timed out six times (circuit `failures=1.0 → 3.0`, `circuit_opened`,
re-admitted after the 30 s reset); 14 min 4 s in total. Read it as capacity, not routing: a probe
answered at 88 s is inside the deadline and outside any usable budget. On the old pin the same
failure cost 3 × 6 × 90 s. The re-run rule's boundary case: the artifact shows exactly one ready
route, and it is the route that just failed — do not re-run on that evidence.

**Why a re-run is the right remedy here and the wrong one for signature 2.** These two failures look
alike — a red required check on a review job — and take opposite actions, so check which one you
have before acting. This failure is *runtime-external*: the pinned source is fine and simply made a
gateway call that failed, so re-executing it issues a fresh call that can succeed. Signature 2 is
*source-staleness*: re-executing pinned source re-executes the same stale source, so a re-run there
is a guaranteed no-op. The discriminator is whether the fix you are waiting on lives on `main`
(signature 2 — you need a new run) or in the transient behaviour of an external service (this
signature — a re-run is exactly right).

**Do not.** Do not blame `served_model`; it is merely the last candidate that failed
(`orchestrator.py:7812`). Do not diagnose it as a provider hang specifically — a 502 here equally
covers upstream 5xx, TLS, DNS and connection failures. Do not add `timeout-minutes` to
`.github/workflows/noema-review.yml`; its absence is deliberate. Do not edit the PR under review.

---

## 4. `reviewed NVIDIA hosted-endpoint cost evidence expired` in contextual-orchestrator

**Symptom.** `BenchmarkContractError: reviewed NVIDIA hosted-endpoint cost evidence expired;
re-review official terms`.

**Mechanism.** `contextual_orchestrator/nim_benchmark.py:113-129` holds `ACTUAL_COST_EVIDENCE`
(`reviewed_at_date` / `valid_until_date`); `_require_current_actual_cost_evidence` (lines 2550-2571)
compares `today or datetime_module.date.today()` against it and fails closed. It is reached only from
`run_benchmark`'s live path (line 3181). Since #1073 (main `a080297`),
`tests/test_nim_benchmark.py:48-53` has an autouse fixture pinning the dates to
`2000-01-01` / `2999-12-31`, so an expired window **no longer fails PR tests**. Before that fixture it
failed five tests on every open PR regardless of diff, via
`contextual-orchestrator/.github/workflows/security.yml:60-62`.

**Do.** Confirm the autouse fixture still exists (open PR #1070 proposes narrowing it to opt-in).
Otherwise re-review <https://docs.api.nvidia.com/nim/docs/product> and update both dates together.

**Do not.** Do not bump `valid_until_date` without that primary-source review — nothing in the code
detects a bare bump, so a date extension silently converts reviewed evidence into fabricated evidence.
Do not read the dates in `tests/test_nim_benchmark_release_acceptance.py` as production evidence; they
are synthetic pricing-scenario fixtures exercised with an injected `today=`, and they must be excluded
from any expired-evidence metric.

---

## 5. `agent-review-runtime-quality` fails on `tests/` files the PR never touched

**Symptom.** In `.github`, the `agent-review-runtime-quality` check fails inside the step
"Verify scheduler and contextual-orchestrator review-repair contracts", with failures in files your
diff never touched — e.g. `tests/test_pr_review_merge_scheduler.py` or
`tests/test_hourly_review_repair_callers.py`. This happens even on a documentation-only PR.

**Mechanism.** `.github/workflows/agent-review-runtime-quality-ci.yml:371-381` runs
`python -m pytest -q --cov=... --cov-branch --cov-fail-under=100` with **no positional path**, and
`pyproject.toml` sets no `testpaths` (only `pythonpath = ["."]`), so collection covers every file
under `tests/`. Any red test in `tests/` fails your PR. The step is gated on
`if: steps.affected_suites.outputs.review_repair == 'true'`, which several documentation paths set
(`docs/product-technical-gap-baseline.md`, `docs/automation/hourly-review-repair.md`,
`docs/doctoring/*-hourly-review-caller.md`). The same unscoped pattern exists in
`agent-mention-router-quality-ci.yml:108` and `repository-metadata-reconcile.yml:100`.

**Do.** Check whether current `main`'s tip passes those same tests. If main is green, merge current
main into the branch, run the FULL suite locally, and push the merge commit. If main is red, land the
repair on main first — precedent: #1877, #1883.

**Do not.** Do not assume "behind main" is the cause: **main is often the broken side**, and merging a
broken main into your branch then loops. Never force-push. Do not treat
`tests/test_docs_only_pr_runner_admission.py` as this signature; it is named explicitly by the strix
step.

**Confirming main's tip is green is necessary but not sufficient.** Two branches can each be
internally consistent and still produce a broken merge, because git only flags the region where the
text overlaps. `contextual-orchestrator#1068` is the worked counterexample: the evidence and its
validator live in *different* regions of the file, so the merge surfaced a conflict in only one of
them, and resolving that one in isolation left the pair inconsistent — with nothing marked to warn
you. After any base merge, run the **full** suite (not the changed-file subset) and grep exhaustively
for every value the merge changed, including in files git reported as clean.

Second live instance, hit directly on `contextual-orchestrator#1030` the same day: the conflict
markers sat at `nim_benchmark.py:115-125` (the evidence dict, where `main` had refreshed dates on
one citation and the branch had replaced the citation), while the validator that enforces the
citation's URL sat at `:2545` — **2,400 lines away, auto-merged to the branch's value with no
marker**. Taking `main`'s side at the marked hunk would have produced a zero-marker file whose
evidence said `docs/product` and whose validator demanded `run-anywhere`. The tell was the three-dot
diff showing the branch changing evidence and validator *together*; the check that settled it was
grepping both URLs after resolution and comparing them, not the absence of markers.

---

## 6. A `check_run` failure whose `head_sha` no longer matches the live PR head

**Symptom.** A `check_run` / `check_suite` failure notification, or a scheduler log line such as
`current head has no OpenCode approval; branch is outdated before review dispatch` or
`current-head OpenCode review requested changes; branch is outdated before re-review`, references a
SHA that is no longer `pull_request.head.sha`.

**Mechanism.** `scripts/ci/pr_review_merge_scheduler_core.py`'s `inspect_pr` calls
`request_branch_update` on four paths: approved head (lines 4648-4685), review requested changes
(4382-4395), no current-head approval before review dispatch (4774-4792), and `restamp_head`
(4687-4730). The failed-check block at line 4563 sits inside `if current_head_approved:`, so failing
checks do **not** stop the second and third paths. `branch_outdated_by_base` (1612-1617) also fires on
the REST compare `behind_by` while GitHub reports `BLOCKED`. The practical effect: by the time an agent
reads a check-failure notification, the branch has frequently already moved.

**Do.** Re-fetch the live `head_sha` and re-read checks and reviews against it before acting.

**And re-fetch it again immediately before you push, not only before you start.** On 2026-09-05 a
CI failure on #1722 was reproduced on head `88775b66`, fixed by merging `main`, and fully validated —
about fifteen minutes of work. By push time the branch's auto-updater had moved the head to
`375013c5`, which was 0 commits behind `main` and already passed the failing tests. Pushing the
prepared merge would have **reverted the newer commit**. The check is free and takes a second:
`git ls-remote origin refs/pull/<n>/head` — if it no longer matches the head you worked from, discard
your merge and re-evaluate on the live head before doing anything else.

**On `CANCELLED`, the scheduler and your triage ask different questions — do not conflate them.**
`FAILED_CHECK_CONCLUSIONS` (line 343) counts `FAILURE`, `ERROR`, `CANCELLED`, `TIMED_OUT` and
`STARTUP_FAILURE`, so a cancelled run **does** block the merge scheduler and you cannot merge past
it. It is not evidence that anything is *wrong with the change*: in this organization cancellation is
overwhelmingly queue sweeping (signature 10). So read it as "this check produced no verdict, and the
scheduler will not merge without one" — never as "this PR is broken". The remedy is a surviving run,
not a code fix.

**Do not.** Never hand-merge base into a PR branch merely because `mergeable_state` reads `behind` —
the scheduler owns that mutation. Act only on a check that has actually COMPLETED with a failure
conclusion.

---

## 7. Required checks sit `queued` for hours and never start

**Symptom.** Nearly every check run on a PR reports `"status": "queued"` with no conclusion, for
hours. This is organization-wide, not per-PR: on 2026-09-05, `.github` had 456 queued runs against 3
in-progress; `contextual-orchestrator` 93; `noema` 53.

**Mechanism.** Actions capacity starvation. A queued check is not a failed one:
`scripts/ci/pr_review_merge_scheduler_core.py:342-343` places `QUEUED` in `RUNNING_CHECK_STATES`,
kept separate from `FAILED_CHECK_CONCLUSIONS`. Each `needs:` stage queues separately, so end-to-end
delay routinely exceeds 8 hours, and some runs queued since 2026-08-19 never started at all. There is
no 4-hour upper bound. The organization-wide ceiling is saturated: 55 of 60 running jobs, with
`.github` holding ~28% of the waiting volume while receiving ~4% of the execution slots.

**Root cause: livelock, not merely slowness.** Of the 100 most recent completed `opencode-review.yml`
runs, **100 were `cancelled`**; the last review to actually run to completion did so at
`2026-09-04T10:14:59Z`. Median run lifetime is **10.8 minutes** against the **4.7+ hours** a run needs
to reach completion, of which 99.9% is queue wait (confirmed by decomposing per-job `created_at` vs
`started_at`). Runs are cancelled by the next push to the same PR *before they are ever assigned a
runner*. The practical consequence is a pacing rule, not a law: **a PR pushed more often than roughly
every five hours will usually fail to reach a verdict.** The 4.7-hour figure is what completion took
under the queue depth and the 60-job runner ceiling measured in §7 on 2026-09-04; it is not an upper
bound, and a shallower queue produces verdicts sooner. If you are iterating on a PR every few minutes,
you are not waiting on the queue — you are resetting it, and each further push sends the run to the
back of it.

**The concurrency configuration is already correct — do not "fix" it.** The group is
`required-opencode-review-{repo}-{PR number}` with `cancel-in-progress: true`, which is right. Do not
switch it to `false`: **62% of the cancelled jobs had not been assigned a runner**, so their
cancellation costs nothing real, and forcing them to run would return all 62% to a queue that is
already at the ceiling.

**What actually holds the slots — measured 2026-09-05T14:27Z.** Occupancy is a property of *jobs*,
not runs: list every in-progress run's jobs (`/actions/runs/{id}/jobs`) and read `started_at` and
`runner_name`. A run "in progress for 10 hours" turned out to be 8 hours of queue plus 2 hours of slot —
`run.created_at` is queue entry, `job.started_at` is slot acquisition. Two discriminators that hold up (peer-verified the same day): a job that never
got a runner reports a placeholder `started_at` equal to the run's `created_at`, so
`completed_at − started_at` on such a job measures queue time, not execution; the reliable tests
are `steps > 0` and `created_at < started_at`. Across the three repositories 18
jobs held runners; 10 were `strix`, and 5 of those were `push`-on-`main` scans of `.github` commits
already superseded (created 04:09–08:44Z, jobs started 12:31–14:25Z, oldest past 2 hours against a
10–30 minute normal scan), with 4 more `push`/`main` scans queued behind them. Mechanism: `strix.yml`'s
workflow-level concurrency key fell back to `github.run_id` for every non-PR event, so each `main` push
was its own group and no newer `main` head ever retired an older scan — the exact coalescing PR heads
get, missing for the branch that moves most (50 pushes in 24 hours, half within 17 minutes of the
previous). Fix: `.github` #1938 scopes `push` events as `push-<ref_name>`. The general lesson: a
`run_id` fallback in a concurrency key is "never coalesce", and it is safe only for events that
genuinely cannot supersede one another (`schedule`, PR-less dispatch); check every event class the
workflow accepts before accepting that fallback.

**Relief you may apply by hand, and the test for it (applied 2026-09-05T16:36Z).** With zero merges
org-wide for 2 h 18 m and six of thirty running `.github` jobs still superseded `push`/`main` Strix
scans, the seven superseded runs were retired and the tip's own scan kept; all seven read
`completed/cancelled` within 20 seconds and six runners returned to the pool. The test has three
parts and all three must hold: the head is an ancestor of the kept tip (`git merge-base
--is-ancestor <sha> origin/main`), nothing consumes the run (a push scan covers the whole tree and
publishes no `strix` status), and the slot has been held longer than a normal scan takes. The
workflow comment names "an explicit operator action or a superseded head" as the two legitimate
reasons to retire a run, so this is inside policy, not around it. Use the MCP `actions_run_trigger`
tool's `cancel_workflow_run` method and verify each run with `actions_get` `get_workflow_run`.
Never apply this to PR scans — a PR scan is consumed by its check, and the PR-scoped group already
retires superseded heads on its own.

**Second application, 2026-09-06T04:36Z, with the pool at zero.** `.github` had 170 queued runs
against 10 in progress. Seven of the ten were `strix` jobs on the pre-bump sidecar holding runners
since 00:10–03:23Z (the five oldest 3 h 45 m–4 h 25 m inside "Run Strix (quick)", signature 3's
bulk-500 shape, with no job timeout by design — `strix.yml:345-350`, `noema-review.yml:261-276` — so
such a job holds its slot until the 6-hour Actions maximum), two were `noema-review` verdict steps
started 03:22Z / 03:47Z, and nothing created after the 03:01Z pin bump had started (11 `noema-review`
runs queued since 03:07Z). Of the 170 queued, 85 were `CodeQL Scan Dispatch` handlers from sibling
repositories rejected at the same actor gate as signature 1's (`codeql-scan-dispatch.yml:142`,
`actor=opencode-agent[bot]` against `github-actions[bot]`): each waits ≈65 minutes for a slot, fails
in 3–6 s, and the source repository re-dispatches — 231 runs in three hours, two or three per SHA —
so their cost is queue position, not runner-minutes. The two `push`/`main` scans (`d9eb9f79b`,
`972b74be2`; both ancestors of `main@efb892692`, whose own push scan was queued) passed the three-part
test and were retired (`33994595180`, `33995072470`, both `completed/cancelled` within 20 s); the
five PR scans were left alone. Note what freeing a slot buys while the pool reads 0 of 12: the next
queued review fails in five minutes with an artifact (signature 3's fail-fast shape) instead of
holding a runner for hours without one — still the right outcome.

**Do.** Read each check's actual conclusion. Truly `queued` → leave it and work elsewhere. A workflow
that was never assigned a runner → escalate on `.github` #712, #1531, #1219. If a PR of yours has
never completed a review cycle, count your own pushes to it before blaming the queue: batch your
remaining changes into one push and then leave the branch untouched long enough for a run to survive.

**Never.** Never push an empty commit, close/reopen a PR, or otherwise re-trigger to "kick" CI. A push
invalidates earlier checks and reviews (`AGENTS.md`, "Actions queue and protected-merge procedure"),
and closing cancels in-flight runs (`.github/workflows/noema-review.yml:78`, `cancel-closed-pr-runs`).
Both discard hours of exact-head evidence and re-enter the queue at the back.

---

## 8. Your PR goes `dirty` while another PR touching the *same file* merged cleanly

**Symptom.** Two or more open PRs append to one document. One of them merges without incident; yours
flips to `mergeable_state: dirty` and an admin merge returns **405**.

**Mechanism.** The collision unit is not the file — it is the **anchor**, the context line git needs
to place a hunk. Measured on `docs/product-technical-gap-baseline.md`: `#1904` appended at
`@@ -3234,0 +3235,119 @@` and `#1868` at `@@ -2775,0 +2776,2 @@`; `#1868` merged **second** into the
same file and stayed clean because its hunk sat in a different region. `#1903` broke — it shares
`#1868`'s anchor, the identical context line `prose" convention already stated in CLAUDE.md.`. So
same-file is not the predictor in either direction: it over-serializes PRs that would never have
touched, and it fails to warn the pair that actually conflicts.

The two unmergeable states are also not equivalent, and this decides whether you must push:

| state | meaning | admin merge with `enforce_admins: false` |
|---|---|---|
| `behind` | base advanced; no textual conflict | **succeeds**, zero pushes needed |
| `dirty` | git-level conflict | **cannot be bypassed** — returns 405 |

So the push-free merge path exists for exactly **one PR per anchor per round**. Everyone after that
needs a real push to resolve, whatever their review state.

**Do.** When claiming an append-heavy document, claim the *anchor*, not the path — e.g. a lane-claim
marker of the form `paths=docs/<file>.md#<section-heading>`. Ordinary code files can stay
path-granular, since edits there are usually region-local. When you do conflict, resolve by keeping
both sides and then verify nothing was silently dropped: diff the exact `##` heading *lists* of
`git show origin/main:<file>` and of your merge result (a count is blind to one section deleted and
another duplicated), then read the complete merge diff before accepting the resolution — altered,
duplicated, or lost content *inside* a section leaves every heading in place. A `--ours`/`--theirs`
resolution produces zero conflict markers while deleting an entire section, which reads as a clean
merge.

**A cheap conflict pre-check whose failure is an anchor bug, not the tool.** `git merge-tree <base>
<a> <b>` piped to `grep -c '^<<<<<<<'` looks like a zero-cost way to ask "will this conflict", and it
returned **0** while a real `git merge --no-commit` conflicted in both `AGENTS.md` and `CLAUDE.md`.
The reason is not that markers are absent. `merge-tree` emits diff-formatted output, so the marker
line is literally `+<<<<<<< .our` — the `^` anchor simply cannot match it:

```bash
git merge-tree "$(git merge-base A B)" A B | grep -c '^<<<<<<<'        # prints 0  — false negative
git merge-tree "$(git merge-base A B)" A B | grep -c '<<<<<<<'         # prints 2  — correct
git merge-tree "$(git merge-base A B)" A B | grep -c 'changed in both' # prints 2  — correct
```

Prefer `changed in both` as the signal: it also covers conflict kinds (mode changes, rename/rename)
that may produce no content markers at all, where even the unanchored grep would read clean.

```bash
git merge-tree "$(git merge-base A B)" A B | grep -c 'changed in both'
```

This is a pre-filter, not a verdict. Where a conclusion rides on the answer, the authority is a real
merge in a scratch worktree — `git worktree add -q --detach /tmp/probe <head> && cd /tmp/probe &&
git merge --no-commit --no-ff origin/main` — then `git merge --abort` and remove it. A zero from the
pre-filter is never evidence that a branch is clean.

**A conflict where neither side is correct: content-hash pins.** `tests/` carries `git hash-object`
pins of workflow files (`grep -rn 'hash-object' tests/` finds them). When both branches edit the
pinned workflow, git auto-merges *the workflow* with no marker and flags only the constant — so the
correct value is derived from a file git never reported as conflicted, and is neither side's. Measured
on #1187: ours `20a83d55`, main's `ade10b37`, and the merged workflow hashing to `2fb3306e`. Choosing
either side yields a resolution with zero conflict markers that fails the pin assertion. Recompute:
`git hash-object <the pinned file>` after the merge, and write that.

The same constant conflicted a second time on #1187 four hours later, when #1932 landed and rewrote
the pinned workflow: ours `2fb3306e` (the previous recompute), main's `26e85559` (#1932's file), and
the merged file hashing to a **third** value, `0a39def5`, because the branch itself also edits that
workflow and git auto-merged it. So the value is never "whichever side is newer" — it is a function
of the merge result, and it has to be recomputed on *every* merge that touches the pinned file. The
live-computed sibling pin in `test_opencode_rust_coverage_toolchain_contract.py` never pays this
cost; a hardcoded pin pays it on every concurrent change.

**Do not.** Do not serialize every PR that touches a shared file — that is the over-correction this
signature exists to prevent, and it stalls work that would have merged fine. Do not assume a clean
merge by a peer means the file is safe for you: they may simply have landed in a different region.

---

## 9. `CodeQL compatibility analysis` fails in seconds, and re-running never helps

**Symptom.** `CodeQL compatibility analysis (actions)` fails in ~7s. The failing steps are
`Request current-head CodeQL scan dispatch` and
`Release runner or enforce current-head CodeQL verdict`. Re-running produces an identical failure;
the run reaches `run_attempt=2` and beyond with no change.

**Mechanism.** The compat job is *designed* to dispatch a separate `CodeQL PR` scan and then fail
fast while awaiting its verdict. That is correct behaviour when the dispatched scan can obtain a
runner. Under queue saturation it cannot. Measured on `contextual-orchestrator#1032`: of the last
eight `CodeQL PR` runs in that repository, **seven were `queued` and the one completed run was
`cancelled`**; the oldest queued run had been created at `06:42Z` and was still queued more than two
and a half hours later. Queue depth at the time: 108 runs in `contextual-orchestrator`, 481 in
`.github`, 344 in `naruon`.

The result is a closed loop: the compat job dispatches → the scan enters a saturated queue and never
starts → no verdict is ever published → the compat job fails fast → a re-run **dispatches again**.
Each re-run cannot succeed *and* enlarges the queue that is causing the failure.

**Do.** Before re-running anything CodeQL-related, check whether the dispatched scans are actually
starting:

```bash
gh api "repos/<owner>/<repo>/actions/runs?per_page=20" \
  --jq '[.workflow_runs[] | select(.name|test("CodeQL";"i")) | {status,conclusion,created_at}]'
```

If those runs are sitting `queued`, treat the compat failure as blocked on runner capacity
(signature 7), not on this PR, and say so on the PR rather than retrying.

**Do not.** Do not re-run while the dispatched scans are queued: it is pure queue amplification, and
it makes the shared condition worse for every other PR in the organization. Do not read the fast
failure as a defect in the PR's code — the job never got as far as analysing it.

---

## 10. Every check on the head reads `cancelled`, and the PR never completes a check cycle

**Symptom.** `get_check_runs` on the current head returns a full set of runs, *all* `status:
"completed"`, with conclusions that are `cancelled` and `skipped` and **no** `failure`. The combined
commit status is `success`. Yet the PR has never once finished a green cycle.

**`cancelled` is not `failure`, and misreading it manufactures a phantom investigation.** Measured on
`#933`: 22 check runs on head `9988c4fc`, all completed — 20 `cancelled`, 2 `skipped`, **zero
`failure`** — with `get_status` returning `state: "success"`. An automated triage pass over this
repository nonetheless labelled it a CI-red failure and produced a careful, entirely wasted analysis
of whose fault the failure was, for a failure that did not exist. Org-wide this is the common case,
not the exception: 18 of the 20 most recent runs of `agent-review-runtime-quality-ci.yml` were
`cancelled`. Read the *conclusion* field, and treat a head with zero `failure` conclusions as not red
no matter how much red-adjacent noise surrounds it.

**The starvation loop.** A bot that auto-merges `main` into a branch on a cadence, combined with the
saturated queue of signature 7, prevents any check from ever concluding — each new head cancels the
runs still queued from the previous one. Measured on `#1722`: `opencode-agent[bot]` merged `main` in
at `2026-09-03T05:49:50Z`, `2026-09-03T18:37:16Z`, `2026-09-05T01:32:00Z` and `2026-09-05T09:18:01Z`.
The per-head outcomes were `093c39b0` cancelled, `6dcba3d3` failure, `ad38c487` failure, `e3b0b2d6`
cancelled, `88775b66` pending. Run `33945594764` sat queued for **4.5 hours without ever executing**
and was then killed at `09:18:08Z` by the arrival of the next auto-update. The PR has not completed a
check cycle once in three days.

**Do.** Establish which head you are on *before* citing any check, and re-establish it after any
delay — on an auto-updated branch the head moves without a human touching it. If the branch is being
auto-updated, the actionable question is not "why did this check fail" but whether the current head
will be allowed to finish before the updater resets it. Escalate the loop itself rather than
triaging its symptoms.

**Do not.** Do not wait on, or tell anyone else to wait on, a specific queued run id: on an
auto-updated branch that run may already have been cancelled by a newer head, and a cancelled run can
never produce a conclusion. Do not respond by merging `main` in yourself — a second updater does not
help, and the branch is already being updated more often than the queue can absorb.

**The converse trap.** `conclusion == "success"` is not a safe filter for "did this run act". While
chasing an unexplained branch update on 2026-09-05, a peer found a run that had acquired a runner and
pushed an update-branch three seconds before the cancel reached it; it reports `cancelled`, and a
filter on `success` hides it. Attribute side effects (pushes, comments, statuses) by looking for the
side effect itself — `steps > 0`, the commit's own pusher, the comment's author — never by conclusion.

---

## 11. Checks are green, no review ever appears, and the scheduler never picks the PR up — it is a draft

**Symptom.** Every check on the head completes, CodeRabbit posts "Draft PR not reviewed", no
`opencode-agent` or `cwl-noema-review` review ever appears, the auto-rebase never touches the branch,
and the PR is never named in a scheduler candidate list. Nothing on the PR says why.

**Mechanism.** Four independent gates treat a draft as out of scope, and none of them reports it on
the PR: `scripts/ci/opencode_review_receipt_gate.py` ("draft must never receive bot APPROVE" — an
approval on a draft is not a formal receipt), `scripts/ci/noema_review_gate.py` ("PR is draft; Noema
review skipped"), `scripts/ci/pr_auto_rebase.py` (`"draft PR"` disqualifies the candidate), and
CodeRabbit's default `auto_review.drafts: false`. Every agent harness in this fleet creates pull
requests as drafts by default, so the mismatch is systemic, not a one-off: measured 2026-09-05T16:20Z,
33 of 138 open `.github` PRs, **16 of 16** open `noema` PRs, and 17 of 64 open `contextual-orchestrator`
PRs were drafts — each un-approvable until someone flips it, however green its checks.

**Do.** Convert your own PR to ready-for-review the moment its local gates pass. The MCP
`update_pull_request` tool takes `draft: false`; REST `PATCH /pulls/{n}` cannot change draft state
(it needs GraphQL `markPullRequestReadyForReview`, which the MCP tool wraps). The `ready_for_review`
event re-fans the required workflows on the same head, so flip before the head accumulates checks you
would rather keep, and never in the middle of a push you are still batching.

**Never.** Never flip a PR you did not open — a draft may be deliberate work in progress, and the
ownership rule is the same as everywhere else in this catalog (the PR body decides). Send the list to
its owners instead. And never flip a draft that carries an owner hold, even one you opened: the
repository owner converted `noema#552` back to draft 27 minutes after a peer flipped it, with no
comment, on an idle PR with clean checks; `contextual-orchestrator#1070` carries an owner comment
"Left as Draft per your instructions — no self-approval, no ready-for-review flip", and `noema#553`'s
body says "Keep Draft until this unchanged exact head receives current terminal CI …" (all three
recorded by `.github` #1912). Before flipping, grep the body and the comment thread for
"keep draft", "ready-for-review", "self-approve": a standing per-PR hold overrides this signature.

**Ownership marker.** Every session on this account commits and opens PRs as the same login, so
`user.login` attributes nothing and a session can only flip drafts it has direct memory of opening.
Put the owner on the PR body's first line when you open it, in the form `.github` PR `#1938` already
uses: `<!-- lane-claim id="<slug>" owner-session="session_…" -->`. It is full-text searchable
(`"owner-session=" in:body`) and it survives squash-merges as PR metadata, so it makes "which of the
open drafts might be mine" a grep instead of a memory test. It is *not* authorization on its own:
anyone who can edit a PR body can paste a marker, so a marker that names your session is a hint to
go and check, never proof. Flip a draft only when all three hold — the marker names your session,
your own record shows you created that PR (the `create_pull_request` result carrying its number in
your transcript, or the PR appearing in `list_pull_requests` for a head branch you pushed), and the
body and thread carry no hold. A marker without that independent record is treated exactly like a
missing one: the PR belongs to someone else.

---

## 12. `required-workflow-bootstrap` fails in ~5 seconds with `Pingora edge policy could not establish complete evidence: … exceeds the size contract`

**Symptom.** The organization-required `opencode-review.yml` run fails in its very first job,
before any review is dispatched, with one line:
`##[error]Pingora edge policy could not establish complete evidence: GitHub content evidence for
<path> exceeds the size contract`, exit code 2. It recurs on every push of the same branch. Seen on
`#1678` (`automation/sbom-inventory`, run `33989047645`) where `<path>` was `docs/sbom/inventory.json`.

**Mechanism.** Deterministic and content-blind — it is not an Nginx finding. `scripts/ci/pingora_edge_policy.py`
reads each changed file's final content through the Contents API, which stops inlining content at
1 MiB and answers `encoding: "none"` with only a `size`. GitHub also omits the diff `patch` for a file
that large, and `_needs_content_scan` treats a missing patch as "must scan", so any text file over
1 MiB that is neither a documentation suffix (`.md`, `.txt`, …) nor a verified binary document
(`.pdf`, `.png`) goes straight to a `ContentSizeExceededError` that only the documentation-PDF path
knows how to absorb; everywhere else it fails the whole check closed. `#1678`'s inventory was
1,148,611 bytes (236 bytes on `main`) and, scanned offline with `main`'s own `scan_content`, carried
zero denied forms — it does not even contain the string `nginx`.

**Do.** Fix the evidence route, not the file: `.github` #1946 follows the Contents response's blob
`sha` to the Git Blobs API (bounded at 11 MiB so the wrapped base64 response fits the existing 16 MiB
reader), binds the blob back to the Contents metadata, and scans the bytes like any inline file.
Until it is on `main`, an affected PR cannot pass this context by re-run, rebase, or any change that
keeps the file over 1 MiB; a base-merge push after the fix lands is what re-binds the required
workflow's trusted source. Before assuming this signature, confirm the file really is clean: the
offline reproduction is `git show <head>:<path>` piped into `scan_content` from `main`'s module (the
module needs `sys.modules[spec.name] = module` before `exec_module`, or its dataclasses fail to
import).

**Do not.** Do not add the path to the documentation exemptions, do not raise `MAX_FILE_BYTES`, and
do not shrink the file to dodge the ceiling — each of those weakens or hides evidence the policy is
supposed to establish. Do not re-run the job: the same source produces the same exit 2 in the same
5 seconds, and the run only re-enters the starved queue (signature 7).

---

## Absence of data flow is not evidence that an edge is safe to cut

Under queue saturation every serial `needs:` hop costs a full queue round (measured at 1.89–2.76 h
per hop), so removing an "ordering-only" edge looks like free latency. Three edges in this repository
share an identical surface signature — the upstream job declares no `outputs`, no downstream job
references its `needs.*`, and it sits above the real work — and they are **not** equally safe:

| edge | verdict |
|---|---|
| `Detect changed scope` gate jobs | load-bearing — the documented mechanism that makes required-workflow path filtering safe |
| `coverage-source-tree` / `coverage-evidence` (#1910) | genuinely ordering-only, safe to parallelise |
| `required-workflow-bootstrap` → `admit-current-head` | load-bearing — a `pull_request_target` trust boundary |

The third rejects untrusted fork PRs and verifies the immutable central policy source before anything
downstream starts. Cutting it lets `admit-current-head` and three downstream jobs run *concurrently
with* the fork check, so an untrusted fork's review begins before the gate can fail it — in a
workflow holding elevated permissions across every repository in the organization.

**So the discriminator is never the edge's shape.** Read every step of the upstream job and ask what
becomes possible if it has not run yet. That is cheap, and it is the whole difference between #1910
(correct) and the same edit applied here (a security regression).

This is the second control in this repository that reads as waste: signature 2's `strix.yml`
`trusted_ref` pin is the first. The common structure is that on `pull_request_target` a control's
**cost is visible in the queue while its benefit is invisible until it is gone**, so optimization
pressure points consistently at the security gates. Note the cheaper alternative that preserves the
guarantee: `noema-review.yml` enforces the same fork boundary as a per-job `if:` condition rather
than an upstream gate job, and a job whose `if:` is false is never created — zero hops, zero runners.

---

## A general rule these three signatures share

Signatures 2, 3 and 9 all present as a red required check on a review job, and two of the three make
a re-run useless. The discriminator is not the error text but the **precondition**:

| the failure is… | re-run? | why |
|---|---|---|
| transient and runtime-external (signature 3: gateway 502) | **yes** | a fresh call can succeed; nothing else must change first |
| pinned to stale source (signature 2: `workflow_sha`) | **no** | the same source re-executes; only a *new run* re-pins |
| waiting on a precondition still unmet (signature 9: queued CodeQL scan) | **no** | re-running re-issues the same unmet request and deepens the queue |

Before re-running any failed check, name the precondition its success depends on and confirm that
precondition has changed. "It might work this time" is not a precondition. Two entries in this
document once prescribed re-running unconditionally; both were wrong, and both were caught by review
rather than by their author.

---

## Research-grounding freshness KPIs

Four cheap, repeatable measurements that catch dated-evidence rot before it fails a gate. Measure them
against `origin/main`, never a working tree (see section 0).

| KPI | Definition | `.github` | `noema` | `contextual-orchestrator` |
|---|---|---|---|---|
| 1. Expired evidence | `valid_until_*` fields whose date is in the past, **excluding** deliberate test fixtures | 0 | 0 | 0 production (4 fixture hits in `tests/test_nim_benchmark_release_acceptance.py`) |
| 2. Silent-aging citations | `as_of*` fields with no paired `valid_until*`, so nothing can ever fail closed | 5 (`scripts/ci/zdr_policy.py:66,90,100,109,117`) | 0 | 0 |
| 3. Open markers | occurrences of `remains open`, `TODO: verify`, `needs-citation`, `unreviewed risk` | 9 | 5 | 42 |
| 4. ADR grounding coverage | fraction of `docs/adr/**` + `docs/planning/adrs/**` files carrying a primary-sources / references section | 3/13 | 2/13 | 29/50 |

Baseline measured 2026-09-05 against the `main` SHAs listed at the top of this document.

Two notes that make these numbers honest rather than alarming:

- KPI 1 is zero in production everywhere. An earlier measurement of this same KPI reported one
  expired production item in `contextual-orchestrator`; that reading came from a stale working tree
  and was wrong — #1073 had already refreshed the window to `2026-10-05` on main. This is exactly the
  failure mode section 0 exists to prevent.
- KPI 2's five hits are the only place in the organization where dated evidence carries no expiry at
  all. `contextual_orchestrator/nim_benchmark.py` is currently the org's only implementation of the
  `reviewed_at` / `valid_until` pair; adopting the same pair in `scripts/ci/zdr_policy.py`'s
  `PROVIDER_ZDR_SCOPE` gives KPI 1 something to measure in `.github` too. `.github` #1916 does this.

### Measuring these without manufacturing a phenomenon

**Count required contexts, not check-runs (peer-corrected 2026-09-05).** "22 checks green" on a head
counted all 34 check-runs, most of them non-required; branch protection evaluates the latest
check-run per *required context* (12 on `.github` `main`), and on those the same head was 7/12 with
two designed-pending CodeQL failures and three queued — the state of every non-draft PR that day
(0 of 105 with a SUCCESS rollup at 16:52Z). Read the required list from
`/branches/main/protection/required_status_checks` (or the merge scheduler's rollup) and take the
latest run per context name; a check-run tally mixes required with informational and old with
current, and overstates readiness every time.

Every KPI above is a count produced by a script, and a counting script fails in a way that looks like
data rather than like an error.

- **Never let a failed API call fall back to a countable value.** `c=$(gh api ... 2>/dev/null || echo
  0)` turns *any* failed call into a genuine-looking zero. In a real sweep of this organization that
  produced rows reading `in_progress_runs=13` with `running_jobs=0` *and* `queued_jobs=0` — an
  impossible combination — and the zeros were initially explained away as "the metric oscillates"
  rather than read as the measurement breaking. Re-measured without the mask, 8 samples over 3
  minutes across 7 repos gave min 27 / max 36 / mean 32.1: stable, no oscillation. Fail loudly, or
  count errors in their own column.
- **In `zsh`, `for x in $var` does not word-split; `for x in $(cmd)` does.** This was the actual
  defect behind the zeros above. `runs=$(gh api ...)` followed by `for id in $runs` iterates **once**
  with the whole newline-separated blob as a single word, producing a malformed request
  (`invalid control character in URL`) which `|| echo 0` then converted into a zero. The same
  session's other measurements used `for id in $(gh api ...)` directly and were correct throughout,
  which is exactly why one session produced both right and wrong numbers. `bash` splits both forms,
  so the broken version looks portable and is not. Use an explicit reader instead:
  `while IFS= read -r id; do ...; done < <(gh api ... --jq '.workflow_runs[].id')`.
- **A correlate is not a cause, even under time pressure.** The zeros above were first attributed to
  REST rate limiting on the strength of `gh api rate_limit` reporting `reset_in=3599s`. That number
  only means the hourly window had just refreshed — it reads the same whether or not you were ever
  throttled. The rate-limit story was published as a cause without being tested, and a peer caught
  it; the shell bug above is what a direct test found. An earlier revision of this very section
  repeated the rate-limit attribution, which is why it is now spelled out here rather than quietly
  replaced. `|| echo 0` was the concealer; it was never the cause.
- **A self-contradictory row is the tell.** Before believing a surprising aggregate, look for a row
  that cannot physically exist. That is cheaper than re-deriving the whole measurement and it
  distinguishes a broken instrument from a real effect.
- **Never diagnose rate limiting from `gh api rate_limit` — that endpoint lies.** Measured with the
  same token at the same moment: `gh api repos/ContextualWisdomLab/.github/branches/main --include`
  returned `403 Forbidden` with `X-Ratelimit-Remaining: 0`, `X-Ratelimit-Used: 5422`,
  `X-Ratelimit-Resource: core`, while `gh api rate_limit --jq '.resources.core'` reported
  `{remaining: 5000, limit: 5000}`. **Read the failing response's own headers**
  (`gh api <endpoint> --include`): `X-RateLimit-Resource` names the exhausted bucket and
  `-Remaining` / `-Used` are authoritative. An earlier revision of this section called this a
  *secondary/burst* limit on the strength of the `rate_limit` reading; it is ordinary **primary
  `core` exhaustion**, and it only looked exotic because the diagnostic everyone reached for was
  contradicted by the real responses.
- **A 403 on one endpoint is not evidence about another — check the bucket, not the URL shape.**
  Quotas are per-resource. In one 0.5-second sweep `core` sat at `0` (so `pulls/`, `issues/`,
  `commits/`, `branches/` and repo metadata all returned 403) while `search` (30/30), `graphql`
  (5000/5000) and the Actions endpoints were untouched and returned 200. Not path prefix, not
  request speed: bucket.
- **The `core` quota is shared per *user*, not per session, and a fleet of agents will drain it.**
  The 403 body names the account (`API rate limit exceeded for user ID …`), so one 5000/hour budget
  covers every concurrent session on that account. Observed here: `X-Ratelimit-Used: 5422` before the
  window reset and `5000` immediately after, still 403 — the refill was consumed within a minute by
  7+ sessions polling PRs, checks, runs and jobs. Waiting for the reset therefore does **not** help
  unless the fleet also slows down. Several of this document's own measurement disputes are
  downstream of this: sweeps that returned silent zeros, `mergeable_state` reads that came back
  `unknown`, and PRs that appeared to carry no checks at all.
- **Prefer paths that spend no quota.** `git show origin/main:<path>` for file contents,
  `raw.githubusercontent.com`, and local `git` for history. Under contention prefer non-`core`
  buckets — `search/issues` and `actions/*` stayed available throughout the episode above.
- **`created_at` is not `updated_at`, and under queue saturation they are hours apart.** `created_at`
  is when a run entered the queue; `updated_at` is when it reached a terminal state. One
  `opencode-review` run here was created `2026-09-04T10:34:34Z` and concluded `2026-09-05T02:12:25Z`
  — a 15.6-hour lifetime. Asking "how long since this pipeline last produced a terminal run" from
  `created_at` reported ~21 hours where `updated_at` gives **~7.4 hours**: the same conclusion, a
  number wrong by 3×, and numbers propagate further than conclusions do. Use `created_at` for queue
  age, `updated_at` for "when did this last conclude". Relatedly, query `status=success` and
  `status=failure` explicitly rather than `status=completed`, because when cancellations dominate
  they bury the terminal signal.
- **When two sessions disagree on one number, stop counting and print records.** This is the reliable
  escape, because at least three independent mechanisms can each turn a sweep into a confident zero —
  shell word-splitting, error masking, and secondary rate limiting — and **none of them announce
  themselves**. Aggregates hide all three; individual job entries carrying `runner_name`,
  `runner_id` and `started_at` cannot be forged by a loop bug or a throttled API. Disagreement about
  a total is resolved by listing the underlying rows, not by re-running the same count more
  carefully.

- **A red baseline is not evidence that `main` is red until you know why it is red.** On 2026-09-05
  a full-suite run of clean `origin/main` for `contextual-orchestrator` reported `2 failed`, and
  "main is broken" was a sentence away from being posted org-wide. The cause was the *sandbox*:
  `opentelemetry-exporter-otlp-proto-http` — a core dependency in `pyproject.toml`, not an extra —
  plus `tiktoken`, `numpy`, `hypothesis` and `fastapi` were simply not installed there. Before
  attributing a baseline failure to the repository, list which declared dependencies your environment
  is missing (`python -c "import <mod>"` per name). The comparison that stays valid in an incomplete
  environment is *baseline versus change in the same environment*: an identical failure set plus only
  additional passes means **no additional observed failures** there, whatever the absolute numbers
  say — and nothing more. It cannot see untested behaviour, the code paths behind the missing
  dependencies, or environment-specific regressions, so the required gates still have to run in a
  supported environment (CI, or a local install of the full declared dependency set) before the
  change counts as verified.
---

## Where the organization's other accumulated know-how lives

- [`.jules/bolt.md`](../../.jules/bolt.md) — dated performance learnings from prior work on
  `scripts/ci/` (regex pre-compilation, `raw_decode` index advancement, N+1 API/subprocess removal),
  each as a `**Learning:**` / `**Action:**` pair.
- [`.jules/sentinel.md`](../../.jules/sentinel.md) — dated security learnings from the same surface
  (HTML-comment breakout in JSON, cross-language redaction parity, `shell=True` "security theater",
  SSRF via redirects), each as `**Vulnerability:**` / `**Learning:**` / `**Prevention:**`.
- `docs/doctoring/` — this directory; per-incident and per-decision records.
- `AGENTS.md` — the binding, tool-agnostic entry point; `CLAUDE.md` complements it for Claude.

Scan `.jules/sentinel.md` before hardening anything under `scripts/ci/`, and `.jules/bolt.md` before
optimizing it. Those records are why several classes of bug are not re-introduced; they only work if
agents other than the one that wrote them actually read them.
