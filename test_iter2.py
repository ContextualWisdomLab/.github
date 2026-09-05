import json
from scripts.ci.opencode_review_normalize_output import iter_json_objects

text = """
Some text
{"hello": "world"} {"test": "ing"}
"""
print(iter_json_objects(text))
