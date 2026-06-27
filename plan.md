1.  **Analyze the Bottleneck:** The `enrich_rest_mergeable_states` function in `scripts/ci/pr_review_merge_scheduler.py` iterates over a list of PRs and sequentially calls `fetch_rest_mergeable_state(repo, int(pr["number"]))` for each. This function issues a network call via `subprocess.run(["gh", "api", ...])`. In a loop, this leads to O(N) I/O wait latency, which is slow for a large number of PRs.
2.  **Proposed Optimization:** Use `concurrent.futures.ThreadPoolExecutor` to run these subprocesses concurrently. As the memory hint states, `subprocess.run` drops the Python GIL, making it an excellent candidate for threading.
3.  **Refactoring Details:**
    *   Import `concurrent.futures`.
    *   Update `enrich_rest_mergeable_states` to execute the `fetch_rest_mergeable_state` calls concurrently using `ThreadPoolExecutor.map` or submitting jobs.
    *   Maintain the existing error handling (catching `RuntimeError`) and mapping of the result to the correct PR.
4.  **Verification:** Run the tests `PYTHONPATH=$(pwd) pytest --cov=scripts/ci tests/` to ensure no functionality is broken and we retain 100% test coverage.
5.  **Pre-commit & Submit:** Add comments, run any formatting/linting scripts, perform pre-commit instructions, and submit the changes.
