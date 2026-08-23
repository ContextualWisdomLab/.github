## 2024-05-19 - Pre-compile regex patterns to optimize deep label-scanning loops
**Learning:** Found a codebase-specific anti-pattern in `scripts/ci/opencode_review_normalize_output.py` where deep label-scanning loops over long review texts were redundantly recompiling regexes for verification labels inside the `label_matches` inner function. This caused measurable overhead in the CI review script.
**Action:** When performing deep text inspection using repetitive substring or pattern matching across a known set of keys or labels, pre-compile the regex objects at the module level.
## 2024-06-21 - Python JSON Decoding Optimization
**Learning:** In Python, string slicing `text[index:]` inside a loop can cause O(N^2) complexity and severe memory copying overhead. When decoding JSON incrementally from a large text blob, `json.JSONDecoder().raw_decode(text, index)` can parse from a given index without slicing. Combining this with `text.find("{", index)` to skip irrelevant characters is significantly faster than `enumerate(text)`.
**Action:** Always prefer `raw_decode(text, index)` and `string.find()` over string slicing and character-by-character iteration when scanning large files for JSON objects.
## 2024-06-23 - `iter_json_objects` 최적화
**Learning:** Python의 `json.JSONDecoder().raw_decode()`를 사용할 때 문자열을 하나씩 순회하며 슬라이싱(`text[index:]`)을 수행하면, O(N^2)의 메모리 할당 및 복사 작업이 발생하여 매우 큰 병목(Bottleneck)이 될 수 있습니다.
**Action:** `str.find("{", index)`를 사용하여 JSON 객체의 시작 위치를 빠르게 건너뛰고, `raw_decode(text, index)`에서 제공하는 `idx` 인자를 활용해 슬라이싱 없이 직접 파싱 수행하여 최적화합니다.
## 2024-11-20 - JSON Decoding Performance - Index Advancement
**Learning:** Even when avoiding string slicing using `json.JSONDecoder().raw_decode(text, index)`, failing to correctly advance the index by ignoring the returned `end` index (`value, _ = decoder.raw_decode(...)`) forces the search loop to repeatedly attempt to decode nested JSON structures (e.g., inner braces `{`) sequentially. This leads to massive O(N^2) time complexity and redundant parsing for large, deeply nested JSON objects.
**Action:** Always capture and use the new end index returned by `raw_decode` (e.g., `value, next_idx = decoder.raw_decode(text, index)`) to jump over the completely parsed object and proceed efficiently.
## 2024-11-21 - JSON Decoding Performance - Fast Path Early Return
**Learning:** When parsing output strings that may contain either pure JSON or prose mixed with JSON, appending successfully parsed full-string JSON objects to a list and continuing to scan character-by-character causes redundant work. The scanner finds the same object again, decodes it again using `raw_decode`, and yields duplicate objects, increasing parsing time to O(N) when it could be O(1) for pure JSON inputs.
**Action:** When a full string parse via `json.loads(text)` succeeds, return immediately (early return) rather than appending and continuing to scan. This acts as a fast path for pure JSON payloads, bypassing the fallback incremental scanning entirely.
## 2026-06-27 - Pre-compile Regex Patterns for Deep Label Scanning
**Learning:** Found a codebase-specific anti-pattern in `scripts/ci/opencode_review_normalize_output.py` where deep label-scanning loops over long review texts were redundantly recompiling regexes for verification labels inside the `label_matches` inner function. This caused measurable overhead in the CI review script.
**Action:** When performing deep text inspection using repetitive substring or pattern matching across a known set of keys or labels, pre-compile the regex objects at the module level.
## 2026-06-25 - Avoid N+1 API blocking in PR checks
**Learning:** In backend processing scripts, synchronous iterations calling an external service, such as fetching `restMergeableState` per PR, cause N+1 API bottlenecks and stall pipeline execution linearly. This matters for PR schedulers handling multiple PRs.
**Action:** Use `concurrent.futures.ThreadPoolExecutor` for independent network calls in a loop when there are multiple items, keep empty and single-item inputs on the cheaper serial path, and bound `max_workers` to avoid API rate limits.
## 2026-06-25 - Avoid N+1 API blocking in PR checks
**Learning:** In backend processing scripts, synchronous iterations calling an external service, such as fetching `restMergeableState` per PR, cause N+1 API bottlenecks and stall pipeline execution linearly. This matters for PR schedulers handling multiple PRs.
**Action:** Use `concurrent.futures.ThreadPoolExecutor` for independent network calls in a loop when there are multiple items, keep empty and single-item inputs on the cheaper serial path, and bound `max_workers` to avoid API rate limits.
## 2024-05-19 - Pre-compile Regex Patterns in Loop-called Functions
**Learning:** In `scripts/ci/pr_review_merge_scheduler.py`, the `scrub_sensitive_data` function was repeatedly compiling multiple regex patterns via `re.sub` for every log line or text scrubbed. This incurs measurable overhead due to cache lookups and object recreation in tightly looped string processing.
**Action:** When using multiple regex replacements inside functions that are called frequently or process large amounts of text, define and pre-compile the regex objects at the module level (e.g., `SENSITIVE_DATA_SCRUB_PATTERNS`) and iterate over them using `pattern.sub()`.
## 2026-07-02 - Credential Masking Security Hole in Subprocess Environments
**Learning:** Found a critical missing credential masking pattern in `scripts/ci/noema_review_gate.py`'s `scrub_sensitive_data` which didn't mask `Authorization: Basic` or `Proxy-Authorization: Basic` tokens unlike its analogous helper in `scripts/ci/pr_review_merge_scheduler.py`. This leaves exception messages and logs vulnerable to exposing sensitive credentials when HTTP operations fail.
**Action:** When implementing credential masking functions that sanitize tracebacks and log messages, ensure the masking scope includes all relevant headers, particularly `Authorization` and `Proxy-Authorization`. Ensure parity across masking helpers across CI scripts to prevent blind spots.
## 2026-06-25 - Python Embedded Regex Compilation
**Learning:** Even when Python is embedded inside a shell script via `cat << 'EOF' | python3`, pre-compiling regular expressions using `re.compile()` at the module level (rather than inline via `re.match`/`re.sub`) remains a valuable micro-optimization because it avoids dictionary lookups in the internal regex cache for frequently called functions processing large text files.
**Action:** Extract inline regular expressions to module-level variables when refactoring embedded Python scripts that parse large CI artifacts or logs.
## 2024-07-11 - Iterative JSON Extraction vs Recursion
**Learning:** In `scripts/ci/opencode_review_normalize_output.py`, deeply recursive nested data processing for extracting JSON dictionaries (such as with LLM outputs where structure is arbitrary) using a recursive `extract_dicts` function causes Python to hit max recursion depth (`RecursionError`) on sufficiently deep structures, and increases runtime overhead due to call stack memory allocations.
**Action:** When extracting data from arbitrary deeply nested dictionaries and lists in Python, use an iterative stack-based approach with `stack.extend()` or `stack.extend(reversed(...))` instead of recursive functions to eliminate recursion depth limitations and reduce overhead.
## 2024-07-25 - Pre-calculate and cache environmental file reads
**Learning:** The `current_changed_files` function in `scripts/ci/opencode_review_normalize_output.py` was being called multiple times per item during JSON structure normalization, leading to redundant I/O reads of `OPENCODE_CHANGED_FILES_FILE`.
**Action:** Use `@functools.lru_cache(maxsize=1)` and return an immutable `frozenset` when repeatedly reading static contextual files within a script's execution lifecycle.
## 2024-11-23 - Memoize File-Based Subprocess Queries in Embedded Python Scripts
**Learning:** Found an N+1 subprocess bottleneck in `scripts/ci/opencode_review_approve_gate.sh` where `changed_new_lines` invoked `git diff` for every finding, even when multiple findings pointed to the same file. Repeatedly shelling out inside loops is a severe performance anti-pattern.
**Action:** When validating multiple findings against the same file, decorate the inspection function with `@functools.cache` and ensure the return value is immutable (e.g., `frozenset` instead of `set`) to avoid redundant subprocess calls.
## 2026-07-09 - Avoid N+1 API blocking in SBOM aggregator
**Learning:** The `collect_inventories` function in `scripts/ci/sbom_inventory_aggregator.py` was fetching SBOMs from the GitHub dependency graph synchronously for every repository in the organization. For large organizations (up to 500 repos), this N+1 network/CLI bottleneck significantly stalled the aggregation workflow.
**Action:** Use `concurrent.futures.ThreadPoolExecutor` to fetch SBOMs concurrently when multiple repositories are provided, bounded by a `max_workers` limit (e.g., 10) to avoid overwhelming the CLI/API, while preserving the fast serial path for single-item inputs.

## 2026-08-09 - [대용량 로그 스캔 시 정규표현식 실행 전 O(N) 서브스트링 검증 선행]
**Learning:** `classify_testthat_failure`에서 테스트 실패 내역이 없는 2MB 로그 파일을 대상으로 정규표현식을 실행하면 약 20ms가 소요되지만, 단순 문자열 검색은 약 1ms만 소요됩니다. 문자열 존재 여부가 정규표현식 매칭의 전제 조건일 때, 콜드 패스(Cold Path)에서 순서 최적화는 매우 큰 성능 차이를 만듭니다.
**Action:** 대용량 텍스트 입력(CI 로그 등)에서 복잡한 정규표현식을 파싱하기 전에 항상 빠른 O(N) 문자열 존재 여부 확인을 먼저 수행하십시오.
## 2026-08-22 - JSONDecoder().raw_decode()를 사용한 JSON 추출 최적화
**Learning:** `scripts/ci/noema_review_gate.py`의 `extract_json_object` 함수에서 `rfind`와 문자열 슬라이싱을 사용하는 기존 방식을 대체할 기회를 발견했습니다. `json.JSONDecoder().raw_decode()`를 사용하면 부분 문자열을 위한 O(N) 메모리 할당을 안전하게 방지하면서, 후행 가비지 텍스트로 인해 발생하는 버그를 완벽하게 차단할 수 있습니다.
**Action:** LLM 응답과 같이 후행에 JSON이 아닌 텍스트가 포함될 수 있는 문자열에서 JSON을 추출할 때는, `rfind("}")` 대신 `json.JSONDecoder().raw_decode()`를 사용하여 파싱 속도를 높이고 더 견고한 코드를 작성하십시오.
