Wait, in `opencode-review.yml`, what did Scorecard complain about?
- `jobLevel 'issues' permission set to 'write'` in `.github/workflows/opencode-review.yml`, Line 453
- `jobLevel 'pull-requests' permission set to 'write'` in `.github/workflows/opencode-review.yml`, Line 454
- `untrusted code checkout 'actions/checkout' without 'persist-credentials: false'` in `.github/workflows/opencode-review.yml`, Line 562
- `pipCommand not pinned by hash` in `.github/workflows/opencode-review.yml`, Line 843

Let's find these lines exactly!
