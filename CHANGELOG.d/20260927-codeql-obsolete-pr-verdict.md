### Correct CodeQL compatibility results after a PR closes or changes

Closed PRs and superseded changes no longer produce a missing-verdict failure
when a queued compatibility check starts later. Current changes still require
a verified scan result; absent or failed evidence continues to block them.
