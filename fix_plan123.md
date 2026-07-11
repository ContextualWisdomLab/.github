Wait, what about `osv-scanner-pr.yml`, `security-scan.yml`, and `strix.yml`?
"File: .github/workflows/osv-scanner-pr.yml, Line: 20"
"File: .github/workflows/security-scan.yml, Line: 41"
"File: .github/workflows/strix.yml, Line: 100"
Did I modify them?
No!
If I didn't modify them, why did Scorecard report them in my PR?
Wait! In the last CI run, Seongho Bae's commit `46f0b35` modified `osv-scanner-pr.yml`, `security-scan.yml`, and `strix.yml`!
And since his commit was merged into `main` and then into my PR branch during the checkout (or GitHub just analyzes the entire PR diff which includes his commit because the branch wasn't rebased properly?), Scorecard saw HIS modifications as part of MY PR!
Oh! Because the system creates the PR from my branch, and if my branch is old, GitHub creates a merge commit with `main`, and then Scorecard analyzes the merge commit?
No, if my branch was created BEFORE his commit, and his commit was pushed to `main`, GitHub's PR diff ONLY shows my changes!
Wait, but if the system MERGED `main` into my branch, then my branch INCLUDES his changes as part of the branch history, but they aren't part of the PR diff... UNLESS my branch was created AFTER his commit!
If my branch was created AFTER his commit, then his commit is in the BASE branch, so it shouldn't be in the PR diff!
Wait, look at the Scorecard run!
If Scorecard failed on these files, it's easier to just FIX THEM than to fight with the PR diff.
Let's fix them!

Alert 1: `opencode-review.yml`, Line 165
`score is 0: untrusted code checkout '${{ github.event.pull_request.head.sha || github.event.inputs.pr_head_sha }}'`
Scorecard complains about `ref: ${{ ... }}` in `actions/checkout` when `repository:` is also specified.
Remediation: Wait, we HAVE to checkout the PR head!
If I add `# scorecard:disable`? Scorecard doesn't support inline suppression!
Wait! The memory says:
"The project uses bandit for security linting of Python scripts. Intentional and documented unsafe behaviors ... can be explicitly suppressed using inline # nosec BXXX comments."
Does it mention Scorecard? No!
Wait! If I look at the Scorecard remediation tip:
`See [this post](https://securitylab.github.com/research/github-actions-preventing-pwn-requests/) for information on avoiding untrusted code checkouts.`
Wait! How did the maintainer fix this in other workflows?
Let's check `strix.yml` to see how it checks out the PR head.
