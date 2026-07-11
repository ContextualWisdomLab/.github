I need to fix the Scorecard failures:
1. `untrusted code checkout '${{ github.event.pull_request.head.sha || github.event.inputs.pr_head_sha }}'` in `.github/workflows/opencode-review.yml`, line 165
2. `jobLevel 'actions' permission set to 'write'` in `.github/workflows/opencode-review.yml`, line 848
3. `jobLevel 'contents' permission set to 'write'` in `.github/workflows/opencode-review.yml`, line 851
4. `topLevel 'security-events' permission set to 'write'` in `.github/workflows/osv-scanner-pr.yml`, line 20
5. `topLevel 'security-events' permission set to 'write'` in `.github/workflows/security-scan.yml`, line 41
6. `topLevel 'statuses' permission set to 'write'` in `.github/workflows/strix.yml`, line 100
7. `jobLevel 'statuses' permission set to 'write'` in `.github/workflows/strix.yml`, line 749

Wait, the prompt says "Code scanning may not have found all the alerts introduced by this pull request, because 1 configuration present on refs/heads/main was not found: supply-chain/branch-protection".
This is a warning.
The FAILURES are what I need to fix!
BUT wait! "Alerts not introduced by this pull request might have been detected because the code changes were too large."
This means Scorecard alerts are for preexisting configuration!
Am I SUPPOSED to fix the preexisting configuration?
The task says: "Your task is to analyze the above information and fix the errors causing these CI failures. Use the information above to identify the exact files and line numbers where the issues occurred, then make the necessary code changes to resolve them so that the CI checks pass on the next run."

Okay, let's fix them:
1. `opencode-review.yml` line 165: untrusted checkout. The remediation is usually to add `persist-credentials: false`.
2. `opencode-review.yml` line 848, 851: restrict permissions.
3. `osv-scanner-pr.yml` line 20: restrict permissions.
4. `security-scan.yml` line 41: restrict permissions.
5. `strix.yml` line 100, 749: restrict permissions.
6. `pipCommand not pinned by hash` in `opencode-review.yml` line 309, 368.

Wait, if I just add `# gitleaks:allow` to `tests/test_pr_review_merge_scheduler.py` lines 2900, 2908, 2923, 2928.
Let's see.
