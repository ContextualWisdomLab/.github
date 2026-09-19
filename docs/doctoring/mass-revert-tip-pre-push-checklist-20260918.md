# Doctoring record: mass-revert PR tips after `merge(main)` (#2171 / #2205 / #2226)

- **Date:** 2026-09-18
- **Subject:** Recurring tips on Bolt performance PRs that look like (or truly are)
  ~15k-LOC control-plane wipes after a `merge(main): sync PR #N for triage` push.
- **Decision record:** none — operational guardrail for workers. Docs-only.
- **Coalesce flag:** leave `OPENCODE_REVIEW_COALESCE_ENABLED=false`. A mass-revert tip
  that deletes `.github/workflows/opencode-review-coalesce-tick.yml` is a tip bug to
  refuse, not a reason to flip the flag on.

## Incidents (live trees, 2026-09-18)

Measured against `origin/main` at `64aa08d7f` (post-`#2213`).

| PR | Tip / commit | Three-dot (`main...tip`) | Two-dot (`main tip`) | Verdict |
|---|---|---|---|---|
| [#2171](https://github.com/ContextualWisdomLab/.github/pull/2171) pre-merge tip `f253f9c64` | intended sanitize fast-path | **2 files, +8/−1** | **107 files, +540/−15711** | Phantom: two-dot only |
| #2171 post-`merge(main)` `3bdf20f0b` | `merge(main): sync PR #2171 for triage` | **2 files, +8/−1** | same order | Healthy sync |
| [#2205](https://github.com/ContextualWisdomLab/.github/pull/2205) restore `542565fe6` | `fix(bolt): restore regex-perf… without mass-reverting main` | **3 files, +19/−7** | same order | Healthy rewrite |
| #2205 current tip `2de12b317` | `Refactor re.split…` on top of restore | **90 files, +471/−12838** | same order | **Real mass-revert tip** (tree 512 files vs main 554) |
| #2205 local triage merge `2941ac58c` | `merge(main): sync PR #2205 for triage` | **3 files, +19/−7** | same order | Healthy sync (not the pushed tip) |
| [#2226](https://github.com/ContextualWisdomLab/.github/pull/2226) tip `ff16764ac` | rewritten bootstrap parallel delta | **3 files, +32/−2** | same order | Healthy rewrite after prior wipe |

On the bad #2205 tip, three-dot deletes control-plane surfaces that main already carries,
including `actions-queue-health.yml`, `opencode-review-coalesce-tick.yml`,
`config/actions_queue_health_repositories.json`, queue-health scripts, and multiple
2026-09-17 doctoring/ADR files. That is not a display illusion: the tip tree is missing
those blobs.

## Two distinct failure modes

1. **Phantom (read error).** `git diff origin/main <stale-tip>` (two-dot) reports
   everything main gained since the fork point as deletions by the PR. AGENTS.md already
   forbids this; `git diff origin/main...<tip>` (three-dot) / `gh pr diff` is the PR
   delta. #2171's pre-merge tip is the clean worked example: ~15.7k two-dot deletions,
   +8/−1 three-dot.
2. **Real mass-revert tip (push error).** A worker “fixes” the phantom, resolves
   `merge(main)` by keeping the stale tip tree, force-pushes an old tip over a clean
   rewrite, or recommits the pre-sync tree on top of a healthy restore. Three-dot then
   correctly shows thousands of deletions. #2205's `2de12b317` (child of the clean
   restore `542565fe6`) is the worked example: one commit removed 42 paths and ~12.8k
   lines that belonged to protected main.

`merge(main)` itself is not the bug when parents are
`(old-tip, origin/main)` and conflict resolution keeps main's unique paths. The same
message string appears on both healthy (`3bdf20f0b`, `2941ac58c`) and catastrophic tips;
only the three-dot size distinguishes them.

## Worker checklist before every push to an open PR tip

Run from the branch that will become the new tip. Refuse the push if any step fails.

1. `git fetch origin main`
2. **Three-dot size check (required):**
   ```bash
   git diff --shortstat origin/main...HEAD
   ```
   Expect a delta on the order of the PR's intended unique change (typically a few
   files / tens of lines for these Bolt PRs). **Abort if deletions are in the
   thousands, if changed-file count jumps into the tens/hundreds without a matching
   product intent, or if control-plane paths appear as `D`.**
3. Spot-check that protected main still exists in the tip tree:
   ```bash
   git cat-file -e HEAD:.github/workflows/opencode-review-coalesce-tick.yml
   git cat-file -e HEAD:.github/workflows/actions-queue-health.yml
   git cat-file -e HEAD:scripts/ci/actions_queue_health.py
   ```
4. Never use two-dot size (`git diff --shortstat origin/main HEAD`) to decide whether
   the tip is safe to push or to “restore” files you think the PR deleted.
5. After `git merge origin/main` (or equivalent sync), re-run steps 2–3 on the merge
   result **before** `git push`. A merge commit message is not evidence of a clean tip.
6. Do not re-apply or cherry-pick the pre-sync tip commit onto a cleaned rewrite; that
   is how #2205 lost the restore.
7. Coalesce stays off: do not set `OPENCODE_REVIEW_COALESCE_ENABLED=true` as part of
   tip repair. Missing coalesce-tick workflow on the tip means the tip is wrong.

Threshold rule of thumb used on these incidents: three-dot deletions ≳ 1_000 on a
narrow perf PR ⇒ mass-revert tip until proven otherwise.

## What this record does not change

- No workflow, scheduler, or coalesce-tick enablement.
- No repair of #2171 / #2205 / #2226 in this commit (docs-only). Tip repair remains a
  separate, evidence-gated rewrite that must pass the checklist above before push.

## References

- ContextualWisdomLab/.github#2171
- ContextualWisdomLab/.github#2205
- ContextualWisdomLab/.github#2226
- `AGENTS.md` — “Verifying a superseded — closing claim” / stale-PR three-dot rule
- `docs/doctoring/coalesce-tick-inert-runner-queue-20260917.md` — coalesce flag remains false
