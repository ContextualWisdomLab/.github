Wait, `security-events: write` is explicitly required to "Upload SARIF to Security > Code Scanning"!
Why does Scorecard complain about `topLevel 'security-events' permission set to 'write'`?
Because it's a TOP-LEVEL permission!
Scorecard wants us to use JOB-LEVEL permissions instead of TOP-LEVEL permissions!
"score is 0: topLevel 'security-events' permission set to 'write'"
"Remediation tip: Visit https://app.stepsecurity.io/secureworkflow ... Tick the 'Restrict permissions for GITHUB_TOKEN'"
This means I should REMOVE `permissions:` from the TOP LEVEL of `.github/workflows/osv-scanner-pr.yml` and `.github/workflows/security-scan.yml` and `.github/workflows/strix.yml`, and put them inside the `jobs:` level!
Let's see if `.github/workflows/osv-scanner-pr.yml` uses permissions at top-level:
```yaml
permissions:
  # Upload SARIF to Security > Code Scanning. See github/codeql-action#2117.
  actions: read
  contents: read
  security-events: write
```
If I move this to `jobs.osv-scan.permissions`?
What about `cancel-closed-pr-runs`? It doesn't need permissions.
Yes! I can move it to the job level!
Let's do this for `osv-scanner-pr.yml`, `security-scan.yml`, and `strix.yml`!
