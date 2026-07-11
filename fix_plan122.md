Wait, `Scorecard` failed because the `supply-chain/branch-protection` check was NOT FOUND?
Wait, if it was NOT FOUND, it means `scorecard-action` did not run it?
Why would `scorecard-action` not run it?
Scorecard requires a PAT (Personal Access Token) to check branch protection!
"publish_results: true"
But it doesn't have a `repo_token` configured! So it uses the default GITHUB_TOKEN, which cannot read branch protections!
But this is on `refs/heads/main`!
Wait, the prompt says "Code scanning may not have found all the alerts introduced by this pull request, because 1 configuration present on refs/heads/main was not found: supply-chain/branch-protection"
This is a standard GitHub Advanced Security warning when a Code Scanning configuration (like a specific tool or category) is missing in the PR run compared to the main branch.
It's NOT why the check failed. The check failed because SCORECARD FOUND CRITICAL AND HIGH ALERTS IN THE CODE I CHANGED!
Wait! "New alerts in code changed by this pull request"
"Security Alerts: 1 critical, 6 high, 2 medium"
Wait! Does my PR introduce these alerts?!
Let's see the annotations:
`[FAILURE] File: .github/workflows/opencode-review.yml, Line: 165`
`Message: score is 0: untrusted code checkout '${{ github.event.pull_request.head.sha || github.event.inputs.pr_head_sha }}'`
Did I modify line 165 of `opencode-review.yml`?
No, my first commit ONLY touched `scripts/ci/validate_opencode_failed_check_review.sh` and `opencode_review_normalize_output.py`.
My second commit ONLY touched `opencode-review.yml` at line 2807! And `tests/test_opencode_agent_contract.py` etc.
Line 165 was ALREADY THERE!
Wait, why did Scorecard report it as "code changed by this pull request"?!
Because Scorecard runs on the WHOLE FILE if the file was modified!
Yes! I modified `.github/workflows/opencode-review.yml`!
So Scorecard analyzed the WHOLE FILE and found all the pre-existing alerts!
And since it found critical alerts in a file I modified, it FAILED MY PR!
Ahhhhh! That's why!
So I MUST FIX the pre-existing alerts in `.github/workflows/opencode-review.yml` in order to pass the PR!
What are the alerts?
1. `opencode-review.yml`, Line 165: untrusted code checkout
2. `opencode-review.yml`, Line 848: jobLevel 'actions' permission set to 'write'
3. `opencode-review.yml`, Line 851: jobLevel 'contents' permission set to 'write'
4. `opencode-review.yml`, Line 309: pipCommand not pinned by hash
5. `opencode-review.yml`, Line 368: pipCommand not pinned by hash
Let's fix them!
