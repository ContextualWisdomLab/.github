Okay, it is restored now!

So `osv-scanner-pr.yml` has:
```yaml
permissions:
  # Upload SARIF to Security > Code Scanning. See github/codeql-action#2117.
  actions: read
  contents: read
  security-events: write
```
I need to change line 20 to `security-events: read`. Wait, if I change the top level, does the job `osv-scan` STILL have `security-events: write`?
Yes!
```yaml
    permissions:
      actions: read
      contents: read
      security-events: write
```
So changing line 20 to `read` or deleting it will satisfy Scorecard and preserve the permission for the job that actually needs it!
I will just replace line 20 with `security-events: read`.
