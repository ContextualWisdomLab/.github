---
name: protected-merge-verification
description: Track a protected GitHub PR through exact-head checks, independent approval, normal auto-merge, and post-merge runtime verification.
argument-hint: "<owner/repo> <pr-number> [scheduled-workflow]"
disable-model-invocation: true
allowed-tools: Bash, Read, Grep
---

# Protected merge verification

## When to use

Use when the user asks to merge or track a PR without Admin bypass, especially “until normal operation.” Do not use it to change branch protection, self-approve, or use `--admin`.

## Inputs / context

1. Gather repository, PR number, target branch, and whether a scheduled workflow must prove normalization.
2. Read current branch protection and current PR state; never rely on an earlier head SHA or an automated-review comment as approval.

## Procedure

1. From any directory, use explicit repository addressing: `gh pr view $1 --repo $0` (adapt arguments to the supplied repo/PR) and `gh api repos/<owner>/<repo>/branches/<base>/protection`.
2. Record current head SHA, draft state, mergeability, required checks, formal approvals, unresolved threads, `required_approving_review_count`, and `require_last_push_approval`.
3. If draft, run `gh pr ready <pr> --repo <owner/repo>` before enabling auto-merge.
4. Verify only checks whose `head_sha` matches the current PR head. A cancelled run, stale run, or CodeRabbit rate-limit response is not passing/approval evidence.
5. If all policy requirements except an independent approval are satisfied, enable/leave normal squash auto-merge. Do not self-approve or use `--admin`.
6. If a parent/stacked PR exists, merge/synchronize the parent first; retarget child to `main` only after parent merge.
7. After merge, fetch the new main SHA and inspect a scheduled/triggered run on that SHA. Report runtime normalization as unverified until a suitable run succeeds.

## Efficiency plan

- Cache repo/PR/base/head in one status note; re-fetch head immediately before each merge decision.
- Prefer structured `gh api` run/job data when web pages are stale. Quote API URLs containing `?` in zsh.
- Stop when an external approval is the only unmet requirement: leave auto-merge and report the concrete policy blocker rather than repeating checks.

## Pitfalls and fixes

- `base branch policy prohibits the merge` -> preserve auto-merge; do not add `--admin`.
- `Pull request ... is a draft` -> mark ready before auto-merge.
- Checks look green but head changed -> discard older evidence and inspect exact-head run.
- `gh run view` outside a checkout fails -> add `--repo <owner/repo>`.

## Verification checklist

- [ ] Exact current PR head recorded.
- [ ] Required checks terminal and successful on that head.
- [ ] Required independent approval and last-push rule satisfied, or the unmet policy is explicitly reported.
- [ ] No self-approval/Admin bypass used.
- [ ] Merge SHA confirmed when merged.
- [ ] If requested, a post-merge scheduled run on new main is successful; otherwise status remains unverified.
