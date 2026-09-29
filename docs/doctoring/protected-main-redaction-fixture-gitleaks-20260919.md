# Protected-main redaction fixture Gitleaks RCA (2026-09-19)

Protected `main@e6334e229581a918e2f22de18733b76fa65d7e71` failed Secret Scan run
`35446163662`, job `105905335612`. The exact pinned command (`gitleaks 8.30.1`,
`--log-opts=e6334e229581a918e2f22de18733b76fa65d7e71`) reproduced exit 2 after
scanning 1,709 reachable commits. Its only results were two `generic-api-key`
findings at lines 18 and 24 of `tests/test_redact_sensitive_log_json_array.py`
in commit `bcff4afd4957a88c4720ff0f9bd6457c9102b950`.

Those literals were synthetic inputs for the log redactor, not credentials.
Commit `41e5be557` already constructs the same test values at runtime, but a
protected-branch full-history scan still visits the superseded source commit.
The repair therefore adds two exact Gitleaks fingerprints: commit, path, rule,
and line are all bound. It does not add a path, rule, or regex allowlist, so a
new secret-like value in that test or anywhere else remains blocking.

The regression contract in
`tests/test_gitleaks_historical_fixture_ignore.py` failed before the exact
fingerprints were added. Acceptance requires that contract, the existing
Gitleaks configuration contracts, and the exact full-history scan to pass.
