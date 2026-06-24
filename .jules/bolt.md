## 2024-06-21 - Python JSON Decoding Optimization
**Learning:** In Python, string slicing `text[index:]` inside a loop can cause O(N^2) complexity and severe memory copying overhead. When decoding JSON incrementally from a large text blob, `json.JSONDecoder().raw_decode(text, index)` can parse from a given index without slicing. Combining this with `text.find("{", index)` to skip irrelevant characters is significantly faster than `enumerate(text)`.
**Action:** Always prefer `raw_decode(text, index)` and `string.find()` over string slicing and character-by-character iteration when scanning large files for JSON objects.
## 2024-06-23 - `iter_json_objects` 최적화
**Learning:** Python의 `json.JSONDecoder().raw_decode()`를 사용할 때 문자열을 하나씩 순회하며 슬라이싱(`text[index:]`)을 수행하면, O(N^2)의 메모리 할당 및 복사 작업이 발생하여 매우 큰 병목(Bottleneck)이 될 수 있습니다.
**Action:** `str.find("{", index)`를 사용하여 JSON 객체의 시작 위치를 빠르게 건너뛰고, `raw_decode(text, index)`에서 제공하는 `idx` 인자를 활용해 슬라이싱 없이 직접 파싱을 수행하여 최적화합니다.

## 2024-06-23 - ReDoS 방지 최적화
**Learning:** `(?:[A-Za-z0-9_.-]+/)+` 패턴을 포함한 정규표현식은 `/`가 연속되는 문자열 등의 특정 조건에서 과도한 백트래킹(Catastrophic Backtracking)을 유발해 ReDoS(Regex Denial of Service)의 원인이 될 수 있습니다.
**Action:** 반복 수량자가 중첩되지 않도록 `(?:[A-Za-z0-9_.-]+/)*` 형태로 수정하거나 백트래킹을 회피하도록 재구성하여 정규표현식 성능 및 안정성을 확보해야 합니다.
