Ah! Wait! Scorecard checks the branch `main` or the current PR. The file in the PR branch is identical to what is in my staging environment.
Why did it complain about lines 453 and 454 then? I didn't see `issues: write` when I `grep`ped!
Wait, if `grep` didn't find `issues: write`, maybe it's not in `.github/workflows/opencode-review.yml` but in another workflow that I didn't check?
Or maybe my `grep` is just not finding it?
Let me do a global search for `issues: write` in `.github/workflows/`!
