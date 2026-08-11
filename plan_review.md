1. Modify `scripts/ci/agent_mention_sweep.py` using `replace_with_git_merge_diff`.
   - Add `import concurrent.futures` to the imports.
   - Extract the per-repository pull request fetching logic from `list_recent_pull_requests` into a helper function `_fetch_repo_pulls` that returns a `list[dict[str, Any]]`.
   - Update `list_recent_pull_requests` to use `concurrent.futures.ThreadPoolExecutor(max_workers=5)` and submit `_fetch_repo_pulls` for each repository, yielding results as they complete using `concurrent.futures.as_completed`.
2. Read the file `scripts/ci/agent_mention_sweep.py` using `read_file` to confirm the edits and new parallelization logic were applied successfully.
3. Update `.jules/bolt.md` by appending a journal entry using `run_in_bash_session` with `cat << 'EOF' >> .jules/bolt.md ... EOF`. The entry will reflect that sequential API calls over multiple repositories create N+1 bottlenecks, and parallelizing them with `ThreadPoolExecutor` significantly speeds up the process.
4. Run the full test suite and check coverage using `run_in_bash_session` with `PYTHONPATH=$PWD python3 -m pytest --cov=scripts/ci tests/`.
5. Complete pre-commit steps to ensure proper testing, verification, review, and reflection are done.
