Ah! `pr-review-fix-scheduler.yml` has `issues: write`!
Let's see if Scorecard complained about `pr-review-fix-scheduler.yml`!
Scorecard output:
"Info: 0: jobLevel 'issues' permission set to 'write': .github/workflows/pr-review-fix-scheduler.yml:99"
Yes! It did!
But wait, why didn't these fail the CI before I started this PR?
Because Scorecard runs on the modified PR!
If it fails Scorecard now, maybe it's because it's set up to block any PR that has a low Scorecard score, and ANY change triggers a scan of the WHOLE repository?
Let me check the `Scorecard` failure from before.
```
Error:     #213: score is 0: topLevel 'security-events' permission set to 'write': .github/workflows/osv-scanner-pr.yml:20
```
Is this the ONLY thing that caused the failure?
Yes, "Error:" lines cause the failure! "Info:" lines are just info!
Let's check the previous output for "Error:".
