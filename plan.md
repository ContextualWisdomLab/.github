1. **Fix `redirect_request` returning `None` instead of raising an error in `scripts/ci/codeql_ghas_configuration_identity.py`**
   - The `_RejectRedirects.redirect_request` method currently returns `None`, which means the `urllib` opener will not follow the redirect but will instead silently return the HTTP 302 response to the caller. This fails to fail-closed and allows bypassing security boundaries.
   - Modify `redirect_request` to raise `urllib.error.HTTPError(_request.full_url, _code, _message, _headers, _file_pointer)`.
2. **Verify changes to `scripts/ci/codeql_ghas_configuration_identity.py`**
   - Use `git diff` to confirm the fix was applied properly.
3. **Fix `redirect_request` returning `None` instead of raising an error in `scripts/ci/strix_evidence_binding.py`**
   - Similar to the above file, `_RejectRedirects.redirect_request` returns `None`.
   - Modify `redirect_request` to raise `HTTPError(_request.full_url, _code, _message, _headers, _file_pointer)`.
4. **Verify changes to `scripts/ci/strix_evidence_binding.py`**
   - Use `git diff` to confirm the fix was applied properly.
5. **Update tests and complete test execution**
   - Fix the mocked tests in `tests/test_github_api_url_boundary.py` that expected `redirect_request` to return `None` without raising an error. The tests should now expect an HTTPError to be raised.
   - Run tests sequentially using:
     - `pip install -r requirements-opencode-review-ci.txt`
     - `bash scripts/ci/test_opencode_fact_gate_contract.sh`
     - `bash scripts/ci/test_strix_quick_gate.sh`
     - `python3 scripts/ci/pr_review_merge_scheduler.py --self-test`
     - `python3 scripts/ci/pr_review_fix_scheduler.py --self-test`
     - `python3 -m coverage run -m pytest tests/`
     - `python3 -m coverage report -m`
6. **Journal learnings**
   - Add a journal entry to `.jules/sentinel.md` documenting that `redirect_request` must raise `HTTPError` rather than returning `None`.
7. **Verify journal changes**
   - Use `git diff` to confirm the journal was correctly modified.
8. **Complete pre-commit steps**
   - Complete pre-commit steps to ensure proper testing, verification, review, and reflection are done.
9. **Submit changes**
   - Submit the PR with the title "🛡️ Sentinel: [HIGH] Fix SSRF bypass by enforcing HTTPError on redirects" and include the required description.
