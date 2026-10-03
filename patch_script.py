import re

with open("tests/test_assert_opencode_reasoning_effort.py", "r") as f:
    content = f.read()

test_func = '''def test_strip_jsonc_comments_prevents_token_fusion() -> None:
    """Test that comments replaced with empty strings do not fuse adjacent tokens."""
    # Ensure numeric tokens do not fuse
    assert guard.strip_jsonc_comments('{"a":1/*x*/2}') == '{"a":1 2}'
    assert guard.strip_jsonc_comments('{"a":-/*x*/1}') == '{"a":- 1}'
    assert guard.strip_jsonc_comments('[1/*x*/.5]') == '[1 .5]'

    # Check that whitespace is retained if it exists
    assert guard.strip_jsonc_comments('{"a":1/* x */2}') == '{"a":1 x 2}'

'''

if "test_strip_jsonc_comments_prevents_token_fusion" not in content:
    with open("tests/test_assert_opencode_reasoning_effort.py", "a") as f:
        f.write(test_func)
