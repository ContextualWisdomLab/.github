Wait, `tests/test_pr_review_merge_scheduler.py` has a test that uses `ghp_abcdef1234567890abcdef1234567890abcdef` to verify that `run()` masks secrets!
But `gitleaks` flags `ghp_abcdef1234567890abcdef1234567890abcdef` as a POTENTIAL SECRET!
Wait, but this is a dummy test secret!
Is there a `# gitleaks:allow` annotation in `tests/test_pr_review_merge_scheduler.py`?
Let's see.
