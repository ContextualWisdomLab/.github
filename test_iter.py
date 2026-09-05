import json
from scripts.ci.opencode_review_normalize_output import iter_json_objects

text = """
Some text
{
  "head_sha": "abc",
  "run_id": "123"
}
Some other text
"""
print(iter_json_objects(text))
