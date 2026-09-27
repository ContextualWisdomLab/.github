### Correct CodeQL compatibility results after a PR closes or changes

Closed PRs and superseded changes no longer produce a missing-verdict failure
when a queued compatibility check starts later. Current changes still require
a verified scan result; absent or failed evidence continues to block them.

The scanner’s AnyIO dependency is pinned to the patched 4.14.2 release, with
verified release hashes and a source/lock parity guard.
