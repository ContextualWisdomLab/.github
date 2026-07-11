Wait, `osv-scanner-pr.yml` already HAS `permissions:` at the job level!
```yaml
    uses: google/osv-scanner-action/.github/workflows/osv-scanner-reusable-pr.yml@9a498708959aeaef5ef730655706c5a1df1edbc2 # v2.3.8
    permissions:
      actions: read
      contents: read
      security-events: write
```
So I can just DELETE the top-level `permissions:` block entirely, EXCEPT that if you don't define top-level permissions, they might default to `read-all` or `write-all` depending on repo settings.
Wait, Scorecard wants `permissions: read-all` at the top level!
Let's see `security-scan.yml`!
