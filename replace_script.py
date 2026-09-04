with open("scripts/ci/opencode_review_normalize_output.py", "r") as f:
    code = f.read()

import re

search_pattern = r'''    index = 0
    while True:
        index = text\.find\("{", index\)
        if index == -1:
            break
        next_index = index \+ 1
        while next_index < len\(text\) and text\[next_index\] in " \\t\\r\\n":
            next_index \+= 1
        if next_index < len\(text\) and text\[next_index\] not in \{'"', "\}"\}:
            index \+= 1
            continue
        try:
            value, new_index = decoder\.raw_decode\(text, index\)
            values\.append\(value\)
            # ⚡ Bolt: Advance index to avoid O\(N\^2\) redundant parsing of nested JSON blocks
            index = new_index
            continue
        except json\.JSONDecodeError:
            pass
        index \+= 1'''

replacement = r'''    index = text.find("{")
    while index != -1:
        next_index = index + 1
        while next_index < len(text) and text[next_index] in " \t\r\n":
            next_index += 1
        if next_index < len(text) and text[next_index] not in {'"', "}"}:
            index = text.find("{", index + 1)
            continue
        try:
            value, new_index = decoder.raw_decode(text, index)
            values.append(value)
            # ⚡ Bolt: Advance index to avoid O(N^2) redundant parsing of nested JSON blocks
            index = text.find("{", new_index)
            continue
        except json.JSONDecodeError:
            pass
        index = text.find("{", index + 1)'''

# Using string replacement instead of regex due to escape issues
code = code.replace(
    '    index = 0\n    while True:\n        index = text.find("{", index)\n        if index == -1:\n            break\n        next_index = index + 1\n        while next_index < len(text) and text[next_index] in " \\t\\r\\n":\n            next_index += 1\n        if next_index < len(text) and text[next_index] not in {\'"\', "}"}:\n            index += 1\n            continue\n        try:\n            value, new_index = decoder.raw_decode(text, index)\n            values.append(value)\n            # ⚡ Bolt: Advance index to avoid O(N^2) redundant parsing of nested JSON blocks\n            index = new_index\n            continue\n        except json.JSONDecodeError:\n            pass\n        index += 1',
    '    index = text.find("{")\n    while index != -1:\n        next_index = index + 1\n        while next_index < len(text) and text[next_index] in " \\t\\r\\n":\n            next_index += 1\n        if next_index < len(text) and text[next_index] not in {\'"\', "}"}:\n            index = text.find("{", index + 1)\n            continue\n        try:\n            value, new_index = decoder.raw_decode(text, index)\n            values.append(value)\n            # ⚡ Bolt: Advance index to avoid O(N^2) redundant parsing of nested JSON blocks\n            index = text.find("{", new_index)\n            continue\n        except json.JSONDecodeError:\n            pass\n        index = text.find("{", index + 1)'
)

with open("scripts/ci/opencode_review_normalize_output.py", "w") as f:
    f.write(code)
