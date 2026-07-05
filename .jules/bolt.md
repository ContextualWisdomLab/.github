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
