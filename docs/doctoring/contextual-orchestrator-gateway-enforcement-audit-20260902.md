# Doctoring record: is contextual-orchestrator enforcement real? (2026-09-02 audit)

- **Date:** 2026-09-02
- **Subject:** The repo owner asked for verification, with actual run
  evidence rather than a read of the YAML/scripts, that OpenCode Review and
  Strix are *실질적으로* (actually, substantively) enforced through the
  contextual-orchestrator gateway — not code that is wired but never
  exercised, and not a path that silently falls back to a non-orchestrator
  route on failure. This record is that evidence, plus one real,
  previously-undocumented merge-governance gap found while tracing how
  review evidence actually reaches a merge decision.
- **Related:** [`docs/adr/0003-contextual-orchestrator-vendored-free-zdr.md`](../adr/0003-contextual-orchestrator-vendored-free-zdr.md)
  (2026-09-02 amendment), [`docs/pr-review-and-merge-procedure.md`](../pr-review-and-merge-procedure.md),
  [`docs/product-goal-directive.md`](../product-goal-directive.md) §8.
- **Exact head examined against:** `6a25bc11d58a2e36da9ccea390ade6ccee57ec4d`
  (branch `claude/contextual-orchestrator-integration-8ec7f8`, identical to
  `main` at audit time).

## Method

Sampled recent `opencode-review.yml` and `strix.yml` runs via
`gh api repos/ContextualWisdomLab/.github/actions/workflows/<file>/runs`
(REST, not GraphQL — GraphQL was rate-limited for this session almost
immediately, consistent with CLAUDE.md's note that the org's GraphQL budget
is shared across many concurrent agents) and pulled job logs with
`gh api repos/ContextualWisdomLab/.github/actions/jobs/<id>/logs`. This repo
is extremely high-churn: of 280 recent non-`push` `strix.yml` runs sampled,
265 (95%) were `cancelled` (a newer push superseding an older head's queued
scan — `cancel-superseded-pr-runs`'s intended, documented behavior) and the
remaining 15 `success` runs were all PR-`closed` events, where `strix.yml`'s
own `if: github.event_name != 'pull_request_target' || github.event.action
!= 'closed'` deliberately skips the `strix` job (confirmed against PR #1348:
head SHA `79d4461f…` matches the run's target SHA, PR `state: closed`,
`merged: true` — this is by design, not a bug: a closed PR needs no fresh
scan, and merge-time evidence is forced separately via `repository_dispatch`
per the workflow's own comments). Finding one real (non-skip, non-cancelled)
execution therefore meant searching completed `failure` runs, since a
genuine multi-minute scan attempt is far more likely to end there than to
land inside the narrow "success and not skipped" window in this environment.

## Item 1 — is the gateway invocation real?

**Yes, confirmed with a real run.** `strix.yml` run `33478956735`
(PR #1558, job `99764086704`, `contextual_orchestrator_review_sidecar.sh`
executing as the `strix` job's sidecar step) shows, in order, from the raw
job log (timestamps UTC, 2026-09-01):

```
09:59:00  provider secrets present: 5 of 5
09:59:00  vendoring contextual-orchestrator @ 8cd99f139915131ba0239bce12a5d6a5fd85394e
09:59:03  installing hash-pinned orchestrator dependencies at 8cd99f13...
10:04:10  using live OpenRouter ZDR endpoint feed
10:04:10  starting review sidecar on 127.0.0.1:18080
10:09:16  healthz and provider-route preflight confirmed after 303s (pid 7117)
10:09:16  sidecar startup warnings (non-fatal): provider_discovery_failed provider=bytez code=http_status_500
10:09:59  gateway chat/completions preflight confirmed (attempt 1/3)
          policy evidence: "pool": "orchestrator/free"
```

This is not a stub: the sidecar cloned the real `contextual-orchestrator`
source at its pinned SHA, installed its hash-pinned lock, ran live model
discovery against the live OpenRouter ZDR feed, and then made one real
HTTP `POST /v1/chat/completions` call through the loopback gateway with a
real bearer token, which returned HTTP 200 with real assistant content
("Reply with just 'OK'." → non-empty response) — the sidecar script parses
and validates the actual response body (`has_text` check in the inline
Python at the end of `contextual_orchestrator_review_sidecar.sh`) before
declaring the preflight confirmed. `provider_discovery_failed
provider=bytez code=http_status_500` in the same log is the pre-existing
Bytez discovery flakiness that PR #1651 (merged same day, see the "Item 3"
note below) targets — logged as a non-fatal warning, not silently absorbed
into a false "all providers healthy" claim.

**What then failed, and how, matters for item 2.** The Strix scanner
process itself (the `ghcr.io/usestrix/strix-sandbox:1.3.0` container),
calling the *same, already-verified-healthy* gateway for its actual security
analysis, could not connect ("LLM CONNECTION FAILED / Could not establish
connection to the language model") on all 3 of its own retry attempts
(66s, 4s, 3s later, with 90s/180s backoffs between). The workflow's own
guard then correctly failed closed:

```
10:16:24  Provider-unavailable Strix attempt 3 reached the retry limit; failing closed.
10:16:24  ::error::Strix could not complete authoritative vulnerability analysis
          because its provider/backend was unavailable ... See the strix-reports
          artifact and run log.
10:16:24  Process completed with exit code 1.
```

Run `33478956735` therefore proves two things at once: (a) the gateway
sidecar layer is real, not stubbed — it performs an actual vendored clone,
actual model discovery, and an actual verified completion; and (b) when the
*scanner's own* connection to that real gateway fails, the job reports
`failure`, not a silently-passing `success` — no fallback/stub/skip path
absorbed this into a green check. Grepping
`scripts/ci/contextual_orchestrator_review_sidecar.sh` and
`scripts/ci/contextual_orchestrator_review_launcher.py` for skip/fallback
branches turns up none that report success without a real completion: every
`fail closed` path in the sidecar script writes the `gateway`/`preflight`
evidence to a JSON report and calls `fail`/`exit 1`, and none of the sampled
runs (see the run inventory the "Method" section above summarizes) show a
`success` conclusion coexisting with an unreachable or unexercised gateway —
the closed-PR `skip` pattern is a distinct, intentional code path (the job
never runs at all, so no fallback/success claim is made either) and was
verified against live PR state rather than assumed.

`opencode-review.yml` itself (the required check named `opencode-review` in
branch protection) is the unprivileged `pull_request_target` bootstrap: it
does not call the sidecar script directly. It exchanges OIDC for the
repository-scoped OpenCode App token and `repository_dispatch`es a
`merge-scheduler` event back to this same repo (line 373-374), which drives
`pr-review-merge-scheduler.yml` → the privileged `opencode-review-dispatch.yml`.
It is `opencode-review-dispatch.yml` that calls
`scripts/ci/contextual_orchestrator_review_sidecar.sh` (confirmed by
`grep -n contextual_orchestrator_review_sidecar .github/workflows/opencode-review-dispatch.yml`,
line 2429) with the identical `contextual-orchestrator/orchestrator/free`
model pinned throughout (lines 3861-4612) — the same script, same pool, as
the `strix` job evidenced above. The bootstrap's own job (line 506) refuses
to report success unless it can confirm "an APPROVED or CHANGES_REQUESTED
[verdict] from opencode-agent on the current head" — i.e. the required
`opencode-review` check is itself gated on a real dispatched verdict landing,
not a local stub. A dedicated `opencode-review-dispatch.yml` job-log pull to
additionally show the OpenCode-side gateway-call text itself was planned but
blocked mid-session by a secondary GitHub REST rate limit shared across the
org's concurrently-running agents (`gh api` began returning `403 API rate
limit exceeded for user ID 8172694` even though `gh api rate_limit` reported
the primary core budget at `5000/5000 remaining` — evidence this is the
abuse-detection secondary limit, not the documented per-hour budget); per
CLAUDE.md's own guidance this was backed off rather than retried in a tight
loop. `opencode-review-dispatch.yml` shares 100% of the
sidecar-provisioning code with the `strix` job evidenced above; nothing in
either workflow calls a different sidecar script or a different pool.

**Confidence on this OpenCode claim, stated explicitly (raised in review):**
direct log evidence of a real gateway call inside `opencode-review-dispatch.yml`
was not collected this session (blocked by the rate limit above), so this is
inferred from shared-code identity with the directly-observed `strix` job,
not independently observed. That inference is strong — it is the identical
script, same line-pinned pool, same job structure — but it is inference, not
observation, and should be labeled that way rather than folded into item 1's
"verified" claim without qualification. Closing this gap directly (pulling
an actual `opencode-review-dispatch.yml` job log once the rate limit clears)
is a small, well-scoped follow-up for the next loop iteration.

## Item 2 — a real, previously-undocumented enforcement gap (not the one hypothesized)

The task's hypothesis was a *code-level* silent-skip (e.g., a missing KV
credential quietly downgrading to a stub that still reports success). That
specific failure mode was not found: every sampled run either genuinely
invoked the gateway or genuinely failed the job. Tracing "does a real
passing check actually gate the merge," however, surfaced a different,
real gap one level up, at the **platform enforcement** layer:

`gh api repos/ContextualWisdomLab/.github/branches/main/protection` (fetched
this session) shows:

```json
"required_status_checks": {
  "strict": true,
  "contexts": ["close-empty", "Detect CodeQL languages", "...", "noema-review",
               "required-workflow-bootstrap", "coverage-evidence", "opencode-review"]
},
"enforce_admins": { "enabled": false }
```

Two things follow from this, both confirmed against live merged PRs (not
inferred):

1. **`strix` is not in the required-status-check context list at all**,
   even though `docs/pr-review-and-merge-procedure.md` line 57 states a
   successor head "must pass OpenCode, Strix, required checks... before
   auto-merge or `--match-head-commit` merge can proceed." Only
   `opencode-review` and `noema-review` are platform-enforced; Strix's
   pass/fail is currently advisory at the GitHub level for `.github`'s own
   `main` branch (confirmed this is not a sibling-repo pattern either: the
   org required-workflow ruleset `18156473` that CLAUDE.md describes as
   applying "in each target repository's context" does not itself appear in
   `gh api repos/ContextualWisdomLab/.github/rules/branches/main`, which
   lists only `deletion`, `non_fast_forward`, and `pull_request` rule types
   for `.github`'s own branch — the ruleset targets sibling repos, per
   `docs/org-required-workflow-rollout.md` line 313's `naruon` example, not
   `.github` itself).
2. **`enforce_admins: false` means a repository-admin-scoped credential
   bypasses *every* required status check, including the two that are
   configured** (`opencode-review`, `noema-review`).

Cross-checked against live evidence: PR #1658 (`fix(strix): remove the 300s
LLM_TIMEOUT cap`, merged `2026-09-02T00:57:07Z`, `merged_by: seonghobae` —
an account with `admin: true` on this repo per `gh api
repos/ContextualWisdomLab/.github --jq .permissions`) merged at a head SHA
(`3196edde85ed7f4a909c3a627af75b47593c7f5e`) whose only recorded
`opencode-review`/`strix` check-runs at or before `merged_at` were
`cancelled` — no `SUCCESS` conclusion exists anywhere in that head's
check-run or classic-commit-status history. `pr-review-merge-scheduler.yml`
runs in the surrounding ~7-minute window were themselves all `cancelled` or
`skipped` (checked via `gh api
.../actions/workflows/pr-review-merge-scheduler.yml/runs` filtered to
`created_at` between `00:50` and `00:58` UTC), meaning the scheduler script's
own `strix_evidence_state()`/OpenCode gate (in
`scripts/ci/pr_review_merge_scheduler.py`, which — per its own docstring —
treats `cancelled` as non-passing and should refuse to call `merge`) most
likely never ran its decision logic to completion for this merge either.
The simplest explanation consistent with all of the above: an
admin-credentialed `gh pr merge` call (whether from the scheduler's
fallback credential chain resolving to an admin-scoped PAT, or a direct
call by some other actor in this heavily concurrent, many-autonomous-agent
org) merged this PR, and GitHub's `enforce_admins: false` let it through
without ever needing the required checks — or the scheduler's own gate — to
show a genuine pass.

**Confidence on the merge-mechanism claim, stated explicitly (raised in
review):** the check-run/status history above is directly observed evidence
that this PR's required checks did not show a genuine pass at merge time —
that part is solid. The specific mechanism (which credential, which caller,
which exact `gh pr merge`/API call) is reconstructed from the available
signals, not observed directly — this session did not have access to
GitHub's organization audit log (a scope-gated API this token was not
granted), which would be the authoritative source for the exact actor and
call. Do not cite the specific-mechanism sentence above as a confirmed fact;
the check-bypass fact itself is confirmed, the mechanism is the most likely
explanation given what was observable.

This is exactly the substance of what the owner asked to rule out ("실질적으로
시행" — actually, substantively enforced, not just wired) — just one layer
higher than the gateway-invocation code path the task named: even a
100%-real gateway call and a correctly-fail-closed job conclusion (as item 1
verified) do not currently gate merges to `.github`'s own `main`, because (a)
Strix's result was never platform-required here, and (b) the one platform
backstop that could catch a scheduler bug or a bypassed scheduler
(`enforce_admins`) is off. Neither `docs/pr-review-and-merge-procedure.md`,
`PR_GOVERNANCE_AUDIT.md`, nor `docs/org-required-workflow-rollout.md` mention
`enforce_admins` or document this as an accepted trade-off — this appears to
be a genuine, previously unrecorded gap, not a documented, deliberate
exception.

### Why this was not fixed directly in this session

Enabling `enforce_admins` and/or adding `strix` to the required-status-check
context list is a GitHub branch-protection (security/system) configuration
change on the org's central governance repository, with real operational
risk: `enforce_admins: true` would also block the repo owner's own
emergency admin merges, and adding `strix` as a hard-required context on
`.github`'s own branch could deadlock exactly the self-modifying-PR case
`scripts/ci/pr_review_merge_scheduler.py`'s `strix_evidence_state()`
docstring already documents (a PR editing `strix.yml` itself can legitimately
fail the *base* branch's trusted CheckRun evidence against its own change).
This is a deliberate owner-level policy decision with organization-wide
blast radius on an actively-merging repository, not a `scripts/ci/` code
defect with a safe, obviously-correct one-line fix — so it is recorded here
as a finding for the owner to decide on, rather than applied unilaterally.

## Item 3 — PR #1651 (Bytez discovery sidecar fix)

By the time this audit reached PR #1651
(`fix(sidecar): discover Bytez free models and suppress expected 413`,
branch `fix/bytez-discovery-sidecar-413`), it had already merged —
`merged_at: 2026-09-02T01:08:37Z`, `merged: true`, merge commit
`9481922748e2c51f36c86400e60d99533189e4be` — moments before this session
queried it (the `mergeable_state: "blocked"` the task described had already
been resolved by another concurrent actor in this org). No action was
needed or taken on this item; it is noted here only because the sidecar log
excerpt above (`provider_discovery_failed provider=bytez
code=http_status_500`, from an *earlier* run predating PR #1651's fix) is
direct evidence of the exact failure class that PR targeted.

## Audit trail

- `docs/adr/0003-contextual-orchestrator-vendored-free-zdr.md` — 2026-09-02
  amendment this record supports.
- Strix run `33478956735` (job `99764086704`), PR #1558 — the gateway
  invocation evidence quoted above.
- `gh api repos/ContextualWisdomLab/.github/branches/main/protection` — the
  `required_status_checks`/`enforce_admins` configuration quoted above
  (live at audit time).
- PR #1658, head `3196edde85ed7f4a909c3a627af75b47593c7f5e` — the merged-
  despite-cancelled-checks example.
- PR #1348 — the closed-PR skip-pattern control example.
- PR #1651, merge commit `9481922748e2c51f36c86400e60d99533189e4be`.
