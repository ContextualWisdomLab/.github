Wait, `git restore` didn't restore it?!
Ah! Because they were ALREADY committed in my previous `submit`?!
No, wait. Did Seongho Bae's commit `46f0b35` have `security-events: read`?
Let me check `git log -p -1 46f0b35 -- .github/workflows/osv-scanner-pr.yml`.
