import re

with open("scripts/ci/opencode_review_normalize_output.py", "r") as f:
    code = f.read()

search_pattern = r'''    start = 0
    end = len\(text\)

    # Fast-path optimization: search space bounds can be dynamically reduced
    # by using the index of the first found candidate, turning an O\(M \* N\)
    # scan into roughly O\(N\) by skipping full-string scans for later candidates\.

    for candidate in candidates:
        idx = text\.find\(candidate, start, end\)
        if idx != -1:
            end = min\(end, idx\)

    if end != len\(text\):
        return end'''

# Wait, `opencode_review_normalize_output.py` doesn't have this either, it's just my journal idea!
# Let me look at `.jules/bolt.md` again.
