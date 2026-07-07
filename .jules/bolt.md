## 2024-06-21 - Python JSON Decoding Optimization
**Learning:** In Python, string slicing `text[index:]` inside a loop can cause O(N^2) complexity and severe memory copying overhead. When decoding JSON incrementally from a large text blob, `json.JSONDecoder().raw_decode(text, index)` can parse from a given index without slicing. Combining this with `text.find("{", index)` to skip irrelevant characters is significantly faster than `enumerate(text)`.
**Action:** Always prefer `raw_decode(text, index)` and `string.find()` over string slicing and character-by-character iteration when scanning large files for JSON objects.
## 2024-06-23 - `iter_json_objects` 최적화
**Learning:** Python의 `json.JSONDecoder().raw_decode()`를 사용할 때 문자열을 하나씩 순회하며 슬라이싱(`text[index:]`)을 수행하면, O(N^2)의 메모리 할당 및 복사 작업이 발생하여 매우 큰 병목(Bottleneck)이 될 수 있습니다.
**Action:** `str.find("{", index)`를 사용하여 JSON 객체의 시작 위치를 빠르게 건너뛰고, `raw_decode(text, index)`에서 제공하는 `idx` 인자를 활용해 슬라이싱 없이 직접 파싱을 수행하여 최적화합니다.
## 2024-11-20 - JSON Decoding Performance - Index Advancement
**Learning:** Even when avoiding string slicing using `json.JSONDecoder().raw_decode(text, index)`, failing to correctly advance the index by ignoring the returned `end` index (`value, _ = decoder.raw_decode(...)`) forces the search loop to repeatedly attempt to decode nested JSON structures (e.g., inner braces `{`) sequentially. This leads to massive O(N^2) time complexity and redundant parsing for large, deeply nested JSON objects.
**Action:** Always capture and use the new end index returned by `raw_decode` (e.g., `value, next_idx = decoder.raw_decode(text, index)`) to jump over the completely parsed object and proceed efficiently.
## 2026-06-25 - Avoid N+1 API blocking in PR checks
**Learning:** In backend processing scripts, synchronous iterations calling an external service, such as fetching `restMergeableState` per PR, cause N+1 API bottlenecks and stall pipeline execution linearly. This matters for PR schedulers handling multiple PRs.
**Action:** Use `concurrent.futures.ThreadPoolExecutor` for independent network calls in a loop, and bound `max_workers` to avoid API rate limits.
## 2024-05-20 - N+1 API blocking in Python REST API scripts
**Learning:** In backend processing scripts, synchronous iterations calling an external service, such as fetching REST API PR node details inside a loop, cause N+1 API bottlenecks and stall pipeline execution linearly.
**Action:** Use `concurrent.futures.ThreadPoolExecutor` combined with `executor.map` for independent network calls in a loop, bounding `max_workers` to avoid API rate limits, while preserving the array return order.
