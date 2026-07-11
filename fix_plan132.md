So Scorecard failed again because I didn't actually fix the Scorecard findings in my previous commit (I only fixed gitleaks).
Now I need to address the Scorecard findings:
1. `untrusted code checkout '${{ github.event.pull_request.head.sha || github.event.inputs.pr_head_sha }}'` in `.github/workflows/opencode-review.yml`, line 165
2. `jobLevel 'actions' permission set to 'write'` in `.github/workflows/opencode-review.yml`, line 848
3. `jobLevel 'contents' permission set to 'write'` in `.github/workflows/opencode-review.yml`, line 851
4. `topLevel 'security-events' permission set to 'write'` in `.github/workflows/osv-scanner-pr.yml`, line 20
5. `topLevel 'security-events' permission set to 'write'` in `.github/workflows/security-scan.yml`, line 41
6. `topLevel 'statuses' permission set to 'write'` in `.github/workflows/strix.yml`, line 100
7. `jobLevel 'statuses' permission set to 'write'` in `.github/workflows/strix.yml`, line 749

Let's do this now.
