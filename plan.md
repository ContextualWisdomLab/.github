1. **Optimize Regex Compilation in `scripts/ci/implementation_completeness_scan.py`**:
   - `nearest_rust_symbol` and `scan_rust_file` compile regular expressions internally (`fn_pattern = re.compile(...)` and `macro_pattern = re.compile(...)`). Because these functions are called during loops over source code, dynamically compiling the regex each time causes measurable overhead.
   - I will extract `RUST_FN_PATTERN` and `RUST_MACRO_PATTERN` to the module level.

2. **Verify changes (Testing and Linting)**:
   - Make the modification to `scripts/ci/implementation_completeness_scan.py` using `replace_with_git_merge_diff`.
   - Verify visually via `cat scripts/ci/implementation_completeness_scan.py | grep -n RUST_FN_PATTERN`
   - Install dependencies: `python3 -m pip install --require-hashes --only-binary=:all: -r requirements-strix-ci-hashes.txt -r requirements-opencode-review-ci-hashes.txt && pip install pytest pytest-cov interrogate mypy bandit black`
   - Run tests: `PYTHONPATH=$(pwd) coverage run -m pytest tests && coverage report --show-missing`
   - Run static analysis: `PYTHONPATH=$(pwd) mypy scripts/ci/implementation_completeness_scan.py`, `bandit -c .bandit -r scripts/ci/implementation_completeness_scan.py`, `black --check scripts/ci/implementation_completeness_scan.py`, and `interrogate scripts/ci/implementation_completeness_scan.py`.

3. **사전 커밋(Pre-commit) 단계 수행**:
   - Ensure proper testing, verification, review, and reflection are done by completing the pre commit steps.

4. **Submit PR**:
   - Create PR using `submit` tool with title `⚡ Bolt: [성능 개선] Rust 스캐너에서 정규표현식 사전 컴파일(Pre-compile) 적용`.
   - All PR description and commits in Korean.
