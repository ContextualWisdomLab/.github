## 2024-06-21 - Python JSON Decoding Optimization
**Learning:** In Python, string slicing `text[index:]` inside a loop can cause O(N^2) complexity and severe memory copying overhead. When decoding JSON incrementally from a large text blob, `json.JSONDecoder().raw_decode(text, index)` can parse from a given index without slicing. Combining this with `text.find("{", index)` to skip irrelevant characters is significantly faster than `enumerate(text)`.
**Action:** Always prefer `raw_decode(text, index)` and `string.find()` over string slicing and character-by-character iteration when scanning large files for JSON objects.
## 2024-06-25 - Review and Merge Conflict Pre-checks
**Learning:** PRs cannot be merged if there are open reviewer change requests (including automated robot reviews) or merge conflicts. Continuous monitoring and resolution of base branch conflicts via `git fetch` and merge/rebase are essential to maintain a mergeable state.
**Action:** Always verify mergeability status and resolve reviewer requests or branch conflicts proactively before attempting to auto-merge PRs.
