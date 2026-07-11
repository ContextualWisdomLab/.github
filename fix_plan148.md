Ah! `pull-requests: write` is on line 854!
Let's look at line 854:
```yaml
  opencode-review:
    needs: [opencode-review-target, cancel-closed-pr-runs, generate-manual-pr-evidence]
    if: ${{ always() && !cancelled() && needs.opencode-review-target.result == 'success' }}
    runs-on: ubuntu-latest
    permissions:
      id-token: write
      models: read
      pull-requests: write
```

Let's check if Scorecard was complaining about this line 854!
The Scorecard output from before said:
`jobLevel 'issues' permission set to 'write'` in `.github/workflows/opencode-review.yml`, Line 453
Wait! In the previous prompt's memory, the Scorecard output was:
"score is 0: jobLevel 'issues' permission set to 'write': .github/workflows/opencode-review.yml:453"
"score is 0: jobLevel 'pull-requests' permission set to 'write': .github/workflows/opencode-review.yml:454"
But my `grep` didn't find `issues: write` at all!
Let me check the diff of `opencode-review.yml`!
