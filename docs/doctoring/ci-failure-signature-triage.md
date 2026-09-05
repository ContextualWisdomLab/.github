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

Baseline for every claim below: `.github` `main@27d7331cc`, `contextual-orchestrator` `main@a080297d`,
`noema` `main@e1ac9d5`, all as of 2026-09-05.

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

**Do not.** Do not reflexively re-run the failed job by hand, and do not "fix" the PR's code — this
failure says nothing about it.

---

## 2. `strix` fails within seconds with `AttributeError: ... no attribute 'asyncio'` or `ModuleNotFoundError: No module named 'httpx2'`

**Symptom.** The required `strix` check dies in 0–2s: a traceback ending in
`AttributeError: 'function' object has no attribute 'asyncio'` **or**
`ModuleNotFoundError: No module named 'httpx2'`, then
`Strix run failed for model 'orchestrator/free' after Ns (exit code 1)`.

**Mechanism.** `.github/workflows/strix.yml:398-400` resolves `trusted_ref` from `job.workflow_sha`,
and line 428 checks the entire trusted Strix source tree out of `ContextualWisdomLab/.github` at that
SHA. That is `.github` main HEAD as of **each run attempt's creation** — not its execution time. A
congestion-queued attempt therefore executes hours later against pre-fix source. The two errors are
different staleness windows: the `AttributeError` means the pin predates `87352d98` (#1783); the
`httpx2` import error means it predates `76969152` (#1851).

**Do.** Confirm on current main that `scripts/ci/strix_timeout_compat.py` resolves the submodule via
`sys.modules["strix.interface.main"]` and that `requirements-strix-ci-hashes.txt` pins
`httpx2==2.12.0`. Then re-run the failed job: the re-run re-pins to main HEAD and runs the newer
`strix.yml`.

**Do not.** Do not patch the consuming repository; its head SHA is not implicated. Do not assume the
re-run repeats identical source — a regression landing between your check and the re-run yields a
new, different error, so re-check main and re-run rather than concluding the fix failed.

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

**Do.** Re-fetch the live `head_sha` and re-read checks and reviews against it before acting. Treat
`FAILURE`, `ERROR`, `CANCELLED`, `TIMED_OUT` and `STARTUP_FAILURE` on a COMPLETED check as failure
(line 343).

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
no 4-hour upper bound.

**Do.** Read each check's actual conclusion. Truly `queued` → leave it and work elsewhere. A workflow
that was never assigned a runner → escalate on `.github` #712, #1531, #1219.

**Never.** Never push an empty commit, close/reopen a PR, or otherwise re-trigger to "kick" CI. A push
invalidates earlier checks and reviews (`AGENTS.md`, "Actions queue and protected-merge procedure"),
and closing cancels in-flight runs (`.github/workflows/noema-review.yml:78`, `cancel-closed-pr-runs`).
Both discard hours of exact-head evidence and re-enter the queue at the back.

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
  `PROVIDER_ZDR_SCOPE` would give KPI 1 something to measure in `.github` too.

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
