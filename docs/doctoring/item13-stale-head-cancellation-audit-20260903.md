# Doctoring record: backlog item 13's stale-head-cancellation hypothesis is refuted; the real evidence is queue depth itself (2026-09-03)

- **Date:** 2026-09-03
- **Subject:** backlog item 13 states "Strix, OpenCode Review, Noema가 Concurrency에 이슈가 없을 것. 한 PR 안에서
  Push가 발생했을 때 이전 HEAD에 관한 Cancel이 발생할 것" (Strix/OpenCode Review/Noema must have no concurrency
  issues; a push within a PR must cancel the previous HEAD's run), citing
  `ContextualWisdomLab/naruon` run `33581213829` / job `100095712154` / PR `#1528` as evidence. The user
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
`#1528`'s full run history) directly from the GitHub API. Every one of the four workflow findings was then
independently re-verified by a second agent instructed to actively try to refute it — re-fetching the same
file fresh, checking for companion cancellation workflows, per-job (not just workflow-level) concurrency
blocks, and verbatim accuracy of every quoted line — before being accepted.

## Result 1: item 13's hypothesis is refuted for all four central workflows — verified, not assumed

| Workflow | Native concurrency scoped by SHA? | Stale-head run gets cancelled? | Mechanism |
|---|---|---|---|
| `strix.yml` | No — group is `strix-<event>-<repo>` only; `cancel-in-progress: false` (deliberate, to preserve scanner logs) | **Yes** | Separate `cancel-superseded-pr-runs` job, same file, fires on `synchronize`/`closed`, lists active runs via the Actions API, matches by workflow name + PR number + head SHA (via `display_title` and `pull_requests[].head.sha`), and POSTs cancel/force-cancel |
| `opencode-review.yml` | Yes — group includes both PR number and exact head SHA (`opencode-review-bootstrap-<repo>-<pr>-<sha>`), `cancel-in-progress: true` | **Yes** | The SHA-scoped group means native cancellation never even needs to fire cross-SHA (a design fix for a real prior incident, `#1568`, where SHA-agnostic grouping let a stale run wrongly cancel a *newer* one); a dedicated `cancel-superseded-opencode-review-runs` job plus an in-loop live-head self-retirement check (60s poll) provide defense-in-depth |
| `noema-review.yml` | No — group is `noema-review-<repo>-<pr>` (PR number only); `cancel-in-progress: true` for `synchronize`/`closed` | **Yes** | Native cancellation alone suffices here (same group, cancel-in-progress true), *and* a same-job "Cancel superseded Noema runs after live-head validation" step independently re-verifies and cancels via the API as defense-in-depth |
| `pr-review-merge-scheduler.yml` | No (PR-number only) for the scheduler's own runs; native cancellation handles those | **Yes, for every repo except `.github` itself** | The `org-queue-sweep` job's hourly cross-repo sweep lists every queued/in-progress run of *any* workflow (reaching Strix/OpenCode/Noema runs directly, not just this scheduler's own), classifies by `head_sha` mismatch against the PR's live head, re-validates immediately before acting, and cancels. Explicitly excludes `ContextualWisdomLab/.github` from its target list — this repo's own PRs rely on Strix/OpenCode/Noema's own (separately verified, correct) mechanisms plus a same-head duplicate-run coalescer (`current-head-run-coalescer.yml`), not this sweep |

All four adversarial verification passes returned `refuted: false` after independently re-fetching the
live files and checking specifically for missed per-job concurrency blocks, companion cancellation
workflows, and misquoted YAML — none were found. One cosmetic inaccuracy was caught and is worth recording
for anyone re-reading `strix.yml`: the investigating agent described a design-rationale comment ("Strix
runs intentionally do not cancel in progress because a pre-job cancellation leaves no scanner log to
review") as adjacent to the `cancel-in-progress: false` line; it is actually ~150 lines earlier, in the
trigger block's `paths-ignore` comment. The design rationale itself is accurate and real — only its
in-file location was misdescribed. This does not change the substantive verdict.

**Conclusion: there is no stale-head-cancellation bug to fix.** Every one of the four central,
required-workflow-ruleset workflows this org's own PR pipeline depends on already reliably retires a
superseded-head run on a new push, through a combination of correctly-scoped native GitHub concurrency and
purpose-built, independently-verified supplementary cancellation jobs — several of which carry their own
design-rationale comments citing prior incidents (`#1568`) that already taught this exact lesson once.
Forcing a "fix" here on the strength of item 13's hypothesis alone, without this evidence, would have meant
inventing a problem that does not exist — the throttle this session has held all along (do not force a
consolidation, or here a fix, that a real look shows is not actually needed) applies.

## Result 2: the cited evidence shows a different, real, and more severe problem — pure queue starvation

The naruon PR `#1528` run history (all 17 recorded runs, pulled live from the GitHub API) shows **zero**
occurrences of two different head SHAs being simultaneously active — every run, across the whole history,
shares the PR's one unchanged head SHA (`cf472cf77fb93325858f485a22e967449d7c387a`). The multi-SHA race
item 13 hypothesized is not what happened here. What actually happened, quoted directly from the API:

- The cited Strix run (`33581213829`) was **created at `2026-09-02T01:54:46Z` but its job did not start
  until `2026-09-03T01:17:10Z`** — a **23-hour-22-minute queue wait** before it even began running, then
  ran for ~14 minutes and was cancelled (superseded by this same investigation's live re-check, not by a
  bug).
- The paired "Required OpenCode Review" run for the identical SHA (`33581213805`), created at the same
  timestamp, **was still `status: queued`, `conclusion: null` when re-checked live on 2026-09-03** — stuck
  queued for **24+ hours with no run at all.**
- Six separate "PR Governance" workflow runs fired for this one unchanged SHA (five `pull_request_target`
  events, one `pull_request_review`). Investigated further after a peer session flagged this as a likely
  redundant-trigger source: `naruon`'s `pr-governance.yml` and `scripts/ci/pr_governance_gate.sh` were
  fetched and read in full (not assumed). Two corrections to the initial framing: (1) the `governance` job
  carries a job-level `if:` that restricts its `check_run`-triggered case to CodeRabbit-named checks only
  — GitHub Actions genuinely cannot filter `check_run` by name at the `on:` trigger level, but the job
  itself is *skipped* (no runner requested) for every non-CodeRabbit check-run completion, so that specific
  vector is not the job-slot waste it first appeared to be; (2) the five observed `pull_request_target`
  firings on one unchanged SHA are near-certainly `labeled`/`unlabeled` (or similar non-`synchronize`)
  events — `synchronize` is the only `pull_request_target` type tied to a new commit, and the SHA never
  changed. More importantly, `pr_governance_gate.sh` evaluates **live** state at the current head on every
  run (required-check states via `gh pr checks`, unresolved review-thread count, CodeRabbit findings via
  check-runs and commit status) — it is explicitly not a pure function of `(head_sha, base_sha)`, so a
  same-head debounce ("skip if nothing changed since the last run at this SHA") would be actively wrong: it
  could leave the gate reporting a stale blocker list from before a required check finished or a review
  landed, a real correctness regression in merge-gating, not merely a missed optimization. No fix was
  attempted for this reason — a safe one needs either confirming which specific labels toggled five times
  on this PR and whether they are governance-irrelevant, or a considered design for distinguishing genuinely
  new gate-relevant information from a redundant re-trigger. Recorded as still open, not fixed.

This is the same root cause `docs/doctoring/actions-plan-concurrency-ceiling-20260903.md` already
identified (a plan-level concurrent-job ceiling), now corroborated with a concrete, painful, individually
named example instead of aggregate counts: a real open PR's real review evidence sat queued for over a day
— not because anything is misconfigured, but because there was nowhere for it to run sooner. This
strengthens, rather than changes, that record's conclusion and its recommendation (a plan-tier decision or
added runner capacity is the actual fix; workflow-file consolidation reduces total triggered runs at the
margin but cannot lift the ceiling).

## What this resolves, and what it does not

- **Resolves:** whether item 13's specific "no cancellation on push" complaint reflects a real
  configuration bug in the four central workflows. It does not — verified, not assumed, across all four,
  with adversarial re-checking. Item 13 should be marked accordingly in `docs/product-technical-gap-baseline.md`.
- **Does not resolve:** why the org's real capacity is saturated to the point of 23-24+ hour stalls — that
  is the plan-level ceiling question `docs/doctoring/actions-plan-concurrency-ceiling-20260903.md` already
  raises as an org-owner billing/plan decision, now with stronger evidence, not a new answer.
- **Open, unverified lead, not a finding:** whether naruon's `pr-governance.yml` fires more often than
  necessary per PR (six runs on one SHA in this one case) is worth a dedicated, evidence-first follow-up
  investigation of that PR's actual label/review event history before concluding anything — recorded here
  so it is not lost, not asserted as confirmed.
- **Bypass-merge authorization:** the user authorized bypass-merge for this investigation as a genuine
  chicken-and-egg case. It is not used here because no fix was found that needed it — this record is itself
  a normal docs-only PR, subject to normal review like any other.

## Audit trail

- Workflow run `wf_eb15dd2b-ad1` (9 agents: 4 investigate, 1 direct-evidence pull, 4 adversarial verify) —
  full per-agent transcripts and the complete unredacted findings/verification JSON live in that run's
  journal.
- `docs/doctoring/actions-plan-concurrency-ceiling-20260903.md` — the root-cause record this evidence
  corroborates.
- `docs/product-technical-gap-baseline.md` — backlog item 13's original text and citation, to be updated
  to reference this record's verdict.
