1. **Import `concurrent.futures` in `scripts/ci/current_head_run_coalescer.py`**:
   - Add `import concurrent.futures` to the imports at the top of the file to enable multithreading.

2. **Parallelize `_associated_prs`**:
   - Currently, it makes sequential API calls: `{number: _fetch_pr(repo, number) for number in sorted(numbers)}` (line ~424).
   - This causes an N+1 API bottleneck.
   - Refactor to use `concurrent.futures.ThreadPoolExecutor(max_workers=min(5, len(numbers)))` to fetch PRs in parallel.

3. **Parallelize `_refresh_siblings`**:
   - Currently, it makes sequential API calls: `[_fetch_run(repo, sibling_run_id) for sibling_run_id in sibling_ids]` (line ~460).
   - Refactor to use `concurrent.futures.ThreadPoolExecutor(max_workers=min(5, len(sibling_ids)))` to fetch runs in parallel.

4. **Run `ruff check --fix scripts/ci/current_head_run_coalescer.py`**:
   - To ensure no unused imports and compliance with formatting rules.

5. **Complete pre commit steps to ensure proper testing, verification, review, and reflection are done**:
   - Run tests and linters.

6. **Submit PR in Korean**:
   - Use the submit tool with a Korean PR title and description.
