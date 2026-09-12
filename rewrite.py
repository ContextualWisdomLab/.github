with open('scripts/ci/assert_opencode_reasoning_effort.py', 'r') as f:
    text = f.read()

new_text = """def strip_jsonc_comments(text: str) -> str:
    \"\"\"Return ``text`` with ``//`` and ``/* */`` comments removed outside strings.

    ``opencode.jsonc`` is genuinely JSONC (it carries explanatory ``//`` notes,
    e.g. above the ``contextual-orchestrator`` provider block), so a plain
    :func:`json.loads` rejects it. Comment markers are only recognized outside
    JSON string literals, so a string value that itself contains ``//`` (the
    ``"$schema": "https://opencode.ai/config.json"`` line) is preserved
    unchanged. Newlines inside removed content are kept so any remaining
    ``json.JSONDecodeError`` still reports an accurate line number.
    \"\"\"
    result: list[str] = []
    in_string = False
    index = 0
    length = len(text)
    last_append = 0
    while index < length:
        char = text[index]
        if in_string:
            if char == "\\\\" and index + 1 < length:
                index += 2
                continue
            if char == '"':
                in_string = False
            index += 1
            continue
        if char == '"':
            in_string = True
            index += 1
            continue
        if char == "/" and index + 1 < length and text[index + 1] == "/":
            result.append(text[last_append:index])
            index += 2
            while index < length and text[index] not in "\\r\\n":
                index += 1
            last_append = index
            continue
        if char == "/" and index + 1 < length and text[index + 1] == "*":
            result.append(text[last_append:index])
            index += 2
            while index + 1 < length and not (
                text[index] == "*" and text[index + 1] == "/"
            ):
                if text[index] in "\\r\\n":
                    result.append(text[index])
                index += 1
            index += 2
            last_append = index
            continue
        index += 1
    result.append(text[last_append:])
    return "".join(result)"""

old_func = text.split("def strip_jsonc_comments")[1].split("def load_config")[0]
old_func = "def strip_jsonc_comments" + old_func

text = text.replace(old_func, new_text + "\n\n\n")

with open('scripts/ci/assert_opencode_reasoning_effort.py', 'w') as f:
    f.write(text)
