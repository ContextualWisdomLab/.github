Ah! The `opencode-review-target` job has `actions: write` and `contents: write`!
Scorecard complains about this.
How to fix?
"Visit https://app.stepsecurity.io/secureworkflow ... Tick the 'Restrict permissions for GITHUB_TOKEN' Untick other options"
If I change them to `read`?
Wait, why does `opencode-review-target` need `actions: write` and `contents: write`?
`actions: write` is needed to cancel workflow runs.
`contents: write` is needed for `pull-requests: write` or auto-merge or pushing commits?
Does `opencode-review-target` push commits?
No, it runs the `opencode-review` agent which posts reviews!
Wait, but what if the agent pushes Autofix commits? Autofix is in a separate workflow! `pr-review-autofix.yml`!
Why does it need `contents: write`?
Maybe `contents: write` is NOT needed?!
Let's see if we can change `actions: write` to `actions: read` and `contents: write` to `contents: read`!
Wait, the `pr-review-merge-scheduler.yml` has:
```yaml
      actions: write
      checks: read
      contents: write
      id-token: write
      pull-requests: write
```
And Scorecard did NOT complain about `pr-review-merge-scheduler.yml`!
Why did it complain about `opencode-review.yml`?
Because `opencode-review.yml` runs on `pull_request_target`!
Scorecard says: "Dangerous workflow patterns: `pull_request_target` with write permissions!"
Yes! `pull_request_target` runs with a privileged `GITHUB_TOKEN`.
If it has `contents: write` and `actions: write`, it's dangerous!
But wait, how can `opencode-review.yml` cancel runs without `actions: write`?
Wait! `opencode-review.yml` has a `cancel-in-progress: true`?
If I just remove `actions: write` and `contents: write`?
If I remove them, will something break?
Let's search for `actions: write` in `.github/workflows/opencode-review.yml`.
