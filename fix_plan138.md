Wait, if I change `security-events: write` to `read`, the jobs that UPLOAD the sarif files will FAIL!
"Upload SARIF to Security > Code Scanning. See github/codeql-action#2117."
If I change `security-events` to `read` globally, the `osv-scan` job will fail!
Wait! The `osv-scanner-pr.yml` already has `permissions: security-events: write` AT THE JOB LEVEL!
```yaml
  osv-scan:
    if: github.event.action != 'closed'
    uses: google/osv-scanner-action/.github/workflows/osv-scanner-reusable-pr.yml@9a498708959aeaef5ef730655706c5a1df1edbc2 # v2.3.8
    permissions:
      actions: read
      contents: read
      security-events: write
```
So I CAN change the TOP LEVEL to `read`, and the job level will OVERRIDE it!
Yes! `permissions` at the job level override the top level.
So changing the top level to `read` or removing the top level `write` is EXACTLY what Scorecard wants!
Wait! I used `sed -i` to replace `write` with `read` globally in the files!
If I did that, it changed it at the JOB LEVEL TOO!
Let's check!
