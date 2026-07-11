Yes, I need to do this carefully.
For `osv-scanner-pr.yml`:
Line 20: `security-events: write` -> change to `read-all` for the top level?
Wait! In `osv-scanner-pr.yml`:
```yaml
permissions:
  # Upload SARIF to Security > Code Scanning. See github/codeql-action#2117.
  actions: read
  contents: read
  security-events: write
```
I can just replace the top level `permissions` block with `permissions: read-all`.
Let's see where the `permissions` block starts.
