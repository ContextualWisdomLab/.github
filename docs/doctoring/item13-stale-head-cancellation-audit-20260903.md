# Doctoring record: backlog item 13's stale-head-cancellation hypothesis is refuted; the real evidence is queue depth itself (2026-09-03)

- **Date:** 2026-09-03
- **Subject:** backlog item 13 states "Strix, OpenCode Review, Noema가 Concurrency에 이슈가 없을 것. 한 PR 안에서
  Push가 발생했을 때 이전 HEAD에 관한 Cancel이 발생할 것" (Strix/OpenCode Review/Noema must have no concurrency
  issues; a push within a PR must cancel the previous HEAD's run), citing
  `ContextualWisdomLab/naruon#1528` (run `33581213829`, job `100095712154`) as evidence. The user
  separately directed: if the org's ~60-concurrent-job ceiling (`docs/doctoring/actions-plan-concurrency-ceiling-20260903.md`)
  is blocking work, trace and resolve the workflow issues that create it, authorizing bypass-merge for this
  specific chicken-and-egg case (a queue-congestion fix that would itself be blocked by queue congestion).
  This record is that trace — and its answer is not the one the hypothesis expected.
- **Decision record:** none in `docs/adr/` — this is a verified negative/confirmatory finding for one specific
  hypothesis, plus a positive, evidence-strengthening finding for a different, already-recorded root cause.
- **PR:** see the PR that carries this commit.

## Method

A 9-agent workflow (4 investigate + 1 direct evidence pull + 4 adversarial verify; `wf_eb15dd2b-ad1`) fetched
`strix.yml`, `opencode-review.yml`, `noema-review.yml`, and `pr-review-merge-scheduler.yml` fresh from
`raw.githubusercontent.com` (not from memory or a prior session's notes), extracted each workflow's exact
`concurrency:` group expression and `cancel-in-progress` value verbatim, searched each file end-to-end for
any supplementary same-file mechanism that cancels a stale prior-head run via the GitHub Actions API, and
reached a verdict on whether a new push to an open PR reliably retires the now-stale run for the previous
head SHA. A separate agent pulled the exact cited evidence (`naruon` run `33581213829`, its job, and PR
ContextualWisdomLab/naruon#1528's full run history) directly from the GitHub API. Every one of the four workflow findings was then
independently re-verified by a second agent instructed to actively try to refute it — re-fetching the same
file fresh, checking for companion cancellation workflows, per-job (not just workflow-level) concurrency
blocks, and verbatim accuracy of every quoted line — before being accepted.

## Result 1: item 13's hypothesis is refuted for all four central workflows — verified, not assumed

| Workflow | Native concurrency scoped by SHA? | Stale-head run gets cancelled? | Mechanism |
|---|---|---|---|
| `strix.yml` | No — group is `strix-<event>-<repo>` only; `cancel-in-progress: false` (deliberate, to preserve scanner logs) | **Yes** | Separate `cancel-superseded-pr-runs` job, same file, fires on `synchronize`/`closed`, lists active runs via the Actions API, matches by workflow name + PR number + head SHA (via `display_title` and `pull_requests[].head.sha`), and POSTs cancel/force-cancel |
| `opencode-review.yml` | Yes — group includes both PR number and exact head SHA (`opencode-review-bootstrap-<repo>-<pr>-<sha>`), `cancel-in-progress: true` | **Yes** | The SHA-scoped group means native cancellation never even needs to fire cross-SHA (a design fix for a real prior incident, `#1568`, where SHA-agnostic grouping let a stale run wrongly cancel a *newer* one); a dedicated `cancel-superseded-opencode-review-runs` job plus an in-loop live-head self-retirement check (60s poll) provide defense-in-depth |
| `noema-review.yml` | No — group is `noema-review-<repo>-<pr>` (PR number only); `cancel-in-progress: true` for `synchronize`/`closed` | **No\*** | The same-job "Cancel superseded Noema runs after live-head validation" step is real and correctly implemented, but it runs too late to prevent the specific failure mode below — this is a **confirmed, unfixed bug**, not a caveat |
| `pr-review-merge-scheduler.yml` | No (PR-number only) for the scheduler's own runs; native cancellation handles those | **Yes, for every repo except `.github` itself** | The `org-queue-sweep` job's hourly cross-repo sweep lists every queued/in-progress run of *any* workflow (reaching Strix/OpenCode/Noema runs directly, not just this scheduler's own), classifies by `head_sha` mismatch against the PR's live head, re-validates immediately before acting, and cancels. Explicitly excludes `ContextualWisdomLab/.github` from its target list — this repo's own PRs rely on Strix/OpenCode/Noema's own (separately verified, correct) mechanisms plus a same-head duplicate-run coalescer (`current-head-run-coalescer.yml`), not this sweep |

**\*`noema-review.yml` has a confirmed, real concurrency bug, raised by Devin Review and independently
adversarially re-verified twice (both the initial investigation and a dedicated refutation attempt failed
to find any flaw) — this is not a hedge, it is a confirmed finding requiring correction to the table row
above and the session's earlier premature "no bug to fix" framing.** GitHub evaluates a workflow's top-level
`concurrency:` block at run-creation time, before any job or step of that run executes, using only the
triggering event's payload. When a new run enters a busy group with `cancel-in-progress: true`, GitHub
cancels whatever is *currently active* in that group unconditionally — as a side effect of the new run
merely starting, not as a result of anything the new run's own logic decides. `noema-review.yml`'s group
(`noema-review-<repo>-<pr>`, no head SHA component) means **every** push to a PR shares one group with every
other push to that same PR. If GitHub's webhook/dispatch pipeline ever processes an older push's
`synchronize` event *after* a newer push's `synchronize` event has already started its run — GitHub does
not guarantee delivery order — the older run's mere entry into the group cancels the newer, valid,
current-head run immediately, **before** the older run ever reaches its own "Reject a stale trigger before
credential or model setup" step. That step then correctly identifies itself as stale and self-aborts — but
only after it has already destroyed the one valid review in flight, leaving the actual current head with no
review at all. Neither the in-job "Cancel superseded Noema runs" step (which only mops up runs with a
strictly *smaller* run id, i.e. genuinely earlier-dispatched ones — it cannot protect a run from a
later-dispatched cancellation) nor any pre-flight gate (none can exist here: GitHub evaluates
`concurrency:` before any job step runs, full stop) closes this. **Strong corroborating evidence that this
is a real, known-avoidable hazard, not a theoretical nitpick:** `strix.yml`'s own `strix` job explicitly sets
`cancel-in-progress: false` specifically to avoid this exact class of problem, with an inline comment
explaining the reasoning, and `opencode-review.yml` closes the identical hazard by scoping its group with
the exact head SHA (a fix already shipped for a real prior incident, `#1568`) rather than relying on native
cancel-in-progress at all. `noema-review.yml` uses neither established mitigation — it is the one central
workflow in this org that still uses the blunt, unguarded pattern the other two deliberately moved away
from. No evidence this has actually fired in production was found or sought (GitHub's own typical event
ordering, not any code in this repository, is the only thing that has prevented it so far) — but "not yet
observed" is not the same claim as "not a bug," and this record's own initial draft conflated the two before
this correction. **Not fixed in this PR** — the safe, precedented fix (adopt `opencode-review.yml`'s
SHA-scoped-group pattern, or an equivalent live-head pre-validation before group entry) is a code change to
a live, security-critical CI workflow gating every PR's required review, and deserves its own focused PR
with a regression test, not a same-breath edit alongside this documentation correction.

All four adversarial verification passes returned `refuted: false` after independently re-fetching the
live files and checking specifically for missed per-job concurrency blocks, companion cancellation
workflows, and misquoted YAML — none were found. One cosmetic inaccuracy was caught and is worth recording
for anyone re-reading `strix.yml`: the investigating agent described a design-rationale comment ("Strix
runs intentionally do not cancel in progress because a pre-job cancellation leaves no scanner log to
review") as adjacent to the `cancel-in-progress: false` line; it is actually ~150 lines earlier, in the
trigger block's `paths-ignore` comment. The design rationale itself is accurate and real — only its
in-file location was misdescribed. This does not change the substantive verdict.

**Conclusion, corrected:** three of the four central, required-workflow-ruleset workflows (`strix.yml`,
`opencode-review.yml`, `pr-review-merge-scheduler.yml`) already reliably retire a superseded-head run on a
new push, through a combination of correctly-scoped native GitHub concurrency and purpose-built,
independently-verified supplementary cancellation jobs. `noema-review.yml` does not — it has the one
confirmed, real, currently-unfixed concurrency bug found in this investigation (above), distinct from item
13's own hypothesis and cited evidence, which remains refuted (`ContextualWisdomLab/naruon#1528` never
exhibited a multi-SHA race; see Result 2). Forcing a fix on the strength of item 13's *own* hypothesis and cited evidence alone
would have meant inventing a problem that does not exist there — but this investigation surfaced a real one
elsewhere in the same file family, and reporting it accurately, not softening it into an "unverified risk,"
is the correct application of the same throttle-agreement discipline (don't force what isn't real; don't
minimize what is).

## Result 2: the cited evidence shows a different, real, and more severe problem — pure queue starvation

The ContextualWisdomLab/naruon#1528 run history (all 17 recorded runs, pulled live from the GitHub API) shows **zero**
occurrences of two different head SHAs being simultaneously active — every run, across the whole history,
shares the PR's one unchanged head SHA (`cf472cf77fb93325858f485a22e967449d7c387a`). The multi-SHA race
item 13 hypothesized is not what happened here. What actually happened, quoted directly from the API:

- The cited Strix run (`33581213829`) was **created at `2026-09-02T01:54:46Z` but its job did not start
  until `2026-09-03T01:17:10Z`** — a **23-hour-22-minute queue wait** before it even began running, then
  ran for ~14 minutes and was cancelled (superseded by this same investigation's live re-check, not by a
  bug).
- The paired "Required OpenCode Review" run for the identical SHA (`33581213805`), created at the same
  timestamp, **was still `status: queued`, `conclusion: null` when re-checked live on 2026-09-03** — stuck
  queued for **24+ hours with no job started.**
- Six separate "PR Governance" workflow runs fired for this one unchanged SHA (five `pull_request_target`
  events, one `pull_request_review`). Investigated further after a peer session flagged this as a likely
  redundant-trigger source: `naruon`'s `pr-governance.yml` and `scripts/ci/pr_governance_gate.sh` were
  fetched and read in full (not assumed). Two corrections to the initial framing: (1) the `governance` job
  carries a job-level `if:` that restricts its `check_run`-triggered case to CodeRabbit-named checks only
  — GitHub Actions genuinely cannot filter `check_run` by name at the `on:` trigger level, but the job
  itself is *skipped* (no runner requested) for every non-CodeRabbit check-run completion, so that specific
  vector is not the job-slot waste it first appeared to be; (2) the five observed `pull_request_target`
  firings on one unchanged SHA came from non-`synchronize` events — `synchronize` is the only
  `pull_request_target` type tied to a new commit, and the SHA never changed. The specific event types were
  not verified (an earlier draft attributed them specifically to `labeled`/`unlabeled`, which is one
  plausible explanation among several non-`synchronize` types and was not confirmed against the PR's actual
  event history — corrected per Devin Review). More importantly, `pr_governance_gate.sh` evaluates **live** state at the current head on every
  run (required-check states via `gh pr checks`, unresolved review-thread count, CodeRabbit findings via
  check-runs and commit status) — it is explicitly not a pure function of `(head_sha, base_sha)`, so a
  same-head debounce ("skip if nothing changed since the last run at this SHA") would be actively wrong: it
  could leave the gate reporting a stale blocker list from before a required check finished or a review
  landed, a real correctness regression in merge-gating, not merely a missed optimization. No fix was
  attempted for this reason — a safe one needs either confirming which specific labels toggled five times
  on this PR and whether they are governance-irrelevant, or a considered design for distinguishing genuinely
  new gate-relevant information from a redundant re-trigger. Recorded as still open, not fixed.

**Precision on what this evidence actually establishes (Devin Review):** the 23h22m and 24+ hour waits prove
queueing occurred; on their own they do not prove a plan-level concurrent-job ceiling is the *exclusive*
cause, only that they are consistent with one. `docs/doctoring/actions-plan-concurrency-ceiling-20260903.md`
treats its own live API counts (jobs `in_progress` vs. `queued`) the same way — as corroboration for that
theory, not as independent proof of it; that record does not claim otherwise, and neither does this one. A
misconfigured scheduler, a starved runner label (a real, separately-documented org history — see this
repository's own `ubuntu-latest` floating-image finding), or some other single-repository cause could in
principle also produce a multi-hour wait for one PR. What narrows toward capacity *here*, specifically, is
that Result 1 above already verified three of the four central workflows' cancellation/scheduling logic is
fully correct, and that the fourth's (`noema-review.yml`'s) confirmed bug has a different failure signature
than what this evidence shows: that bug wrongly *cancels* a still-current run outright, whereas Result 2's
runs sat *queued* for 23h22m/24+ hours with no cancellation at all. A run stuck queued that long, never
cancelled, is not the symptom the confirmed bug produces — so this specific wait is still not explained by a
known bug in this PR's own review pipeline, which narrows the remaining explanation toward capacity rather
than proving it by elimination of every other conceivable cause.

With that precision stated, this evidence is consistent with, and corroborates, the root cause
`docs/doctoring/actions-plan-concurrency-ceiling-20260903.md` already identified (a plan-level concurrent-job
ceiling) — now with a concrete, individually named example instead of only aggregate counts: a real open
PR's real review evidence sat queued for over a day, with no workflow-configuration defect found to explain
it. This strengthens, rather than changes, that record's conclusion and its recommendation (a plan-tier
decision or added runner capacity is the actual fix; workflow-file consolidation reduces total triggered
runs at the margin but cannot lift the ceiling).

## What this resolves, and what it does not

- **Resolves:** whether item 13's specific "no cancellation on push" complaint reflects a real
  configuration bug *as evidenced by its own cited example* (`ContextualWisdomLab/naruon#1528`). It does not — that PR
  never exhibited a multi-SHA race; see Result 2. Item 13 should be marked accordingly in
  `docs/product-technical-gap-baseline.md`, alongside the confirmed finding below rather than instead of it.
- **Confirmed finding, fix proposed but not yet merged (raised by Devin Review, adversarially re-verified
  twice with no refutation found):** `noema-review.yml`'s native `cancel-in-progress` can cancel a genuinely
  current run when GitHub processes an older push's `synchronize` event after a newer one — GitHub does not
  guarantee webhook/dispatch delivery order, and this workflow's concurrency group has no head-SHA component
  to make such an inversion harmless. See the corrected caveat under Result 1's table for the full mechanism
  and the corroborating evidence that `strix.yml` and `opencode-review.yml` both deliberately avoid this
  exact pattern already. **Fix pushed as commit `31e46db` on `ContextualWisdomLab/.github#1661`** (a peer
  session ported `opencode-review.yml`'s own `#1568` fix: the event's head SHA added as a third group-key
  segment), independently re-verified against that branch — but `31e46db` is not reachable from `main`
  (`git compare main...31e46db` reports `diverged`, `#1661` still open), and `main`'s live `noema-review.yml`
  still has the pre-fix group with no head-SHA component. Do not mark this closed on `main` until `#1661`
  merges — the same "proposed vs. landed" distinction Devin caught once already on this record's sibling PR
  (`.github#1765`'s phase-labeling citation).
- **Open, unverified lead, not a finding:** whether naruon's `pr-governance.yml` fires more often than
  necessary per PR (six runs on one SHA in this one case) is worth a dedicated, evidence-first follow-up
  investigation of that PR's actual label/review event history before concluding anything — recorded here
  so it is not lost, not asserted as confirmed.
- **Investigated and refuted (raised by Devin Review, adversarially re-verified with no refutation found):**
  a claim that `strix.yml`'s `pull_request_target: paths-ignore:` list suppresses `cancel-superseded-pr-runs`
  (a job in the same file, sharing the same trigger) for a push whose diff touches only ignored paths,
  leaving the previous head's Strix scan running indefinitely. `strix.yml`'s own internal gap is real — that
  half of the claim is correct, and there is no escape hatch inside that file. But a sibling required
  workflow, `pr-review-merge-scheduler.yml`, has no `paths-ignore` at all and fires unconditionally on the
  same event; its `scan-pr-queue` job unconditionally calls `cancel_stale_pr_runs()`
  (`scripts/ci/pr_review_merge_scheduler.py`), which cancels any active run in the repository whose
  `head_sha` no longer matches the PR's live head — regardless of which workflow created that run —
  typically within the same push event, with a 30-minute local-cron backstop specifically for
  `ContextualWisdomLab/.github` (whose own comment already documents this as the reason `org-queue-sweep`'s
  `.github` exclusion is safe) and an hourly org-wide sweep backstop for every sibling repository. The
  scenario does not leave a stale Strix scan running indefinitely anywhere.
- **Bypass-merge authorization:** the user authorized bypass-merge for this investigation as a genuine
  chicken-and-egg case. It is not used here because no fix was found that needed it for item 13's own
  hypothesis or the paths-ignore claim; the one confirmed bug found (`noema-review.yml`'s concurrency
  ordering hazard, above) is deliberately left for its own dedicated fix PR rather than bypass-merged in
  alongside documentation. This record is itself a normal docs-only PR, subject to normal review like any
  other.

## Audit trail

- Workflow run `wf_eb15dd2b-ad1` (9 agents: 4 investigate, 1 direct-evidence pull, 4 adversarial verify) —
  full per-agent transcripts and the complete unredacted findings/verification JSON live in that run's
  journal.
- Workflow run `wf_68f78449-bb6` (4 agents: 2 investigate, 2 adversarial verify) — the follow-up
  investigation of the two substantive Devin Review findings above (`noema-review.yml`'s confirmed
  concurrency bug, `strix.yml`'s refuted paths-ignore claim); full per-agent transcripts and the complete
  unredacted findings/verification JSON live in that run's journal.
- `docs/doctoring/actions-plan-concurrency-ceiling-20260903.md` — the root-cause record this evidence
  corroborates.
- `docs/product-technical-gap-baseline.md` — backlog item 13's original text and citation, to be updated
  to reference this record's verdict.
