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
updating the variable; neither is a per-PR action.

**Do not.** Do not reflexively re-run the failed job by hand, and do not "fix" the PR's code — this
failure says nothing about it.

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
job listed 21 free-pool candidates, all `nvidia_nim` / `nvidia_nim_sub` — one upstream — so the
failover loop cannot leave a stalled upstream whatever its retry budget (root cause and design
directions: `.github` #1903). While the stall is measurably ongoing (failure rate near 50% over the
last hour), a re-run is a coin flip that costs another 3–36 minutes of a slot the queue is starving
for. Measure before re-running: list `noema-review.yml` runs from the last hour and grep the failed
jobs' logs for `HTTP Error 502`; re-run once the rate has dropped, not while it is high.

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
runner*. The practical consequence is a hard rule: **a PR pushed more often than roughly every five
hours can never pass review.** If you are iterating on a PR every few minutes, you are not waiting on
the queue — you are resetting it, and no amount of further pushing will produce a verdict.

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
both sides and then verify nothing was silently dropped: compare `grep -c '^## '` between
`git show origin/main:<file>` and your merge result. A `--ours`/`--theirs` resolution produces zero
conflict markers while deleting an entire section, which reads as a clean merge.

**A cheap conflict pre-check whose failure is an anchor bug, not the tool.** `git merge-tree <base>
<a> <b>` piped to `grep -c '^<<<<<<<'` looks like a zero-cost way to ask "will this conflict", and it
returned **0** while a real `git merge --no-commit` conflicted in both `AGENTS.md` and `CLAUDE.md`.
The reason is not that markers are absent. `merge-tree` emits diff-formatted output, so the marker
line is literally `+<<<<<<< .our` — the `^` anchor simply cannot match it:

```
$ git merge-tree "$(git merge-base A B)" A B | grep -c '^<<<<<<<'        # 0  — false negative
$ git merge-tree "$(git merge-base A B)" A B | grep -c '<<<<<<<'         # 2  — correct
$ git merge-tree "$(git merge-base A B)" A B | grep -c 'changed in both' # 2  — correct
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
its owners instead.

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
  additional passes means the change is clean, whatever the absolute numbers say.
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
